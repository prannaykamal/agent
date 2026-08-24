from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage

from src.api.server import app
from src.db import init_db
from src.harness.graph import node_agent
from src.harness.llm_router import (
    LLMRouteResult,
    LLMSelector,
    normalize_model_name,
    normalize_provider,
    resolve_llm_selector,
    resolve_primary_llm,
    resolve_secondary_from_job_payload,
    resolve_secondary_llm,
)


client = TestClient(app)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "phase4_router.db"
    mem_file = tmp_path / "MEMORY.md"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    monkeypatch.setattr("src.config.MEMORY_PATH", mem_file)
    init_db(db_file)
    return db_file


def _route(role, provider, model_name, llm=None, available=True):
    return LLMRouteResult(
        selector=LLMSelector(
            role=role,
            provider=provider,
            model_name=model_name,
            temperature=0.7 if role == "primary" else 0.3,
            context_window=128000,
            source="test",
        ),
        llm=llm,
        available=available,
        fallback_used=False,
        error=None if available else "unavailable",
    )


def test_normalize_provider_alias_and_unknown_fallback():
    assert normalize_provider("xai") == "grok"
    assert normalize_provider(None) == "openai"
    assert normalize_provider("") == "openai"

    route = resolve_primary_llm(provider="unknown-provider", model_name=None)
    assert route.selector.provider == "openai"
    assert route.fallback_used is True


def test_primary_and_secondary_selectors_use_role_defaults():
    primary = resolve_llm_selector(role="primary", provider="openai")
    secondary = resolve_llm_selector(role="secondary", provider="openai")

    assert primary.model_name == "GPT-5.5"
    assert secondary.model_name == "gpt-4o-mini"
    assert primary.context_window == 128000
    assert secondary.context_window == 128000


def test_provided_model_name_is_preserved_and_context_window_comes_from_catalog():
    selector = resolve_llm_selector(
        role="primary",
        provider="anthropic",
        model_name="Claude Opus 4.1",
    )

    assert selector.model_name == "Claude Opus 4.1"
    assert selector.context_window == 200000
    assert normalize_model_name("gemini", "Gemini 2.5 Pro", "secondary") == "Gemini 2.5 Pro"


def test_missing_credentials_return_unavailable_without_raising(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "your_openai_api_key_here")

    primary = resolve_primary_llm(provider="openai", model_name="gpt-4o")
    secondary = resolve_secondary_llm(provider="openai", model_name="gpt-4o-mini")

    assert primary.available is False
    assert primary.llm is None
    assert secondary.available is False
    assert secondary.llm is None


def test_node_agent_uses_primary_route_only(monkeypatch):
    fake_llm = MagicMock()
    fake_llm.bind_tools.return_value.invoke.return_value = AIMessage(content="primary response")

    def fail_secondary(*args, **kwargs):
        raise AssertionError("secondary route must not be used by node_agent")

    monkeypatch.setattr(
        "src.harness.graph.resolve_primary_llm",
        lambda provider, model_name: _route("primary", provider, model_name, llm=fake_llm),
    )
    monkeypatch.setattr("src.harness.llm_router.resolve_secondary_llm", fail_secondary)

    result = node_agent(
        {
            "messages": [HumanMessage(content="hello")],
            "session_id": "phase4-node-agent",
            "provider": "openai",
            "model_name": "gpt-4o-mini",
            "loop_count": 0,
            "loop_events": [],
            "tools_used": [],
        }
    )

    assert result["messages"][-1].content == "primary response"
    assert fake_llm.bind_tools.called


def test_mixed_provider_chat_uses_primary_provider_for_response(monkeypatch, temp_db):
    monkeypatch.setattr(
        "src.harness.graph.resolve_primary_llm",
        lambda provider, model_name: _route(
            "primary",
            provider,
            model_name,
            llm=None,
            available=False,
        ),
    )

    response = client.post(
        "/api/chat",
        json={
            "message": "Hello mixed provider",
            "session_id": "phase4_mixed_provider",
            "provider": "openai",
            "model_name": "gpt-4o",
            "secondary_provider": "anthropic",
            "secondary_model_name": "claude-3-5-haiku-latest",
        },
    )

    assert response.status_code == 200
    assert "[Openai/gpt-4o Primary LLM (Offline)]" in response.json()["response"]


def test_mixed_provider_job_resolves_secondary_provider_from_payload(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "your_anthropic_api_key_here")
    payload = {
        "models": {
            "primary_provider": "openai",
            "primary_model_name": "gpt-4o",
            "secondary_provider": "anthropic",
            "secondary_model_name": "claude-3-5-haiku-latest",
        }
    }

    route = resolve_secondary_from_job_payload(payload)

    assert route.selector.role == "secondary"
    assert route.selector.provider == "anthropic"
    assert route.selector.model_name == "claude-3-5-haiku-latest"
    assert route.available is False


def test_primary_unavailable_returns_offline_fallback(monkeypatch):
    monkeypatch.setattr(
        "src.harness.graph.resolve_primary_llm",
        lambda provider, model_name: _route(
            "primary",
            "anthropic",
            "claude-3-5-sonnet-latest",
            llm=None,
            available=False,
        ),
    )

    result = node_agent(
        {
            "messages": [HumanMessage(content="hello offline")],
            "session_id": "phase4-offline",
            "provider": "anthropic",
            "model_name": "claude-3-5-sonnet-latest",
            "loop_count": 0,
            "loop_events": [],
            "tools_used": [],
        }
    )

    assert "[Anthropic/claude-3-5-sonnet-latest Primary LLM (Offline)]" in result["messages"][-1].content


def test_secondary_unavailable_does_not_break_chat(monkeypatch, temp_db):
    def fail_secondary(*args, **kwargs):
        raise AssertionError("secondary route should not be used by chat")

    monkeypatch.setattr("src.harness.llm_router.resolve_secondary_llm", fail_secondary)

    response = client.post(
        "/api/chat",
        json={
            "message": "Chat should not need secondary",
            "session_id": "phase4_secondary_unavailable",
            "provider": "openai",
            "model_name": "gpt-4o-mini",
            "secondary_provider": "anthropic",
            "secondary_model_name": "claude-3-5-haiku-latest",
        },
    )

    assert response.status_code == 200
    assert "response" in response.json()


def test_chat_title_generation_does_not_call_secondary_route(monkeypatch, temp_db):
    def fail_secondary(*args, **kwargs):
        raise AssertionError("secondary LLM must not be used for chat titles")

    monkeypatch.setattr("src.harness.models.get_secondary_llm", fail_secondary)
    monkeypatch.setattr("src.harness.llm_router.resolve_secondary_llm", fail_secondary)

    response = client.post(
        "/api/chat",
        json={
            "message": "Create a budget plan for Q3 team lunch",
            "session_id": "new_phase4_title_test",
            "provider": "xai",
            "model_name": "grok-2-latest",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert set(
        [
            "session_id",
            "session_title",
            "response",
            "retrieval_triggered",
            "retrieved_memories",
            "pending_approval_id",
            "approval_status",
            "iterations",
            "tools_used",
            "loop_events",
            "loop_trace",
        ]
    ).issubset(data.keys())
    assert data["session_id"] != "new_phase4_title_test"
    assert "Q3" in data["session_id"] or "Budget" in data["session_id"] or "Create" in data["session_id"]
