"""AI_PROVIDER picks the app-wide default provider; explicit choices still win."""

import pytest

from src.harness.llm_router import normalize_model_name, normalize_provider, resolve_llm_selector
from src.harness.models import get_active_provider, get_model_catalog, get_model_instance
from src.memory.config import load_memory_config


@pytest.mark.parametrize("value,expected", [(None, "openai"), ("gemini", "gemini"), ("GEMINI", "gemini"), ("openai", "openai"), ("claude", "openai")])
def test_active_provider_reads_ai_provider(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("AI_PROVIDER", raising=False)
    else:
        monkeypatch.setenv("AI_PROVIDER", value)

    assert get_active_provider() == expected


def test_gemini_switch_sets_defaults_everywhere(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "gemini")

    cfg = load_memory_config()
    selector = resolve_llm_selector("primary")

    assert (cfg.primary_llm.provider, cfg.primary_llm.model_name) == ("gemini", "gemini-3.8-flash")
    assert (cfg.secondary_llm.provider, cfg.secondary_llm.model_name) == ("gemini", "gemini-3.5-flash-lite")
    assert (selector.provider, selector.model_name) == ("gemini", "gemini-3.8-flash")
    assert normalize_model_name("gemini", None, "secondary") == "gemini-3.5-flash-lite"
    assert get_model_catalog()["active_provider"] == "gemini"


def test_explicit_choices_still_override_the_switch(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.setenv("PRIMARY_PROVIDER", "openai")
    monkeypatch.setenv("PRIMARY_MODEL", "gpt-4o")

    cfg = load_memory_config()

    assert (cfg.primary_llm.provider, cfg.primary_llm.model_name) == ("openai", "gpt-4o")
    assert normalize_provider("openai") == "openai"
    assert resolve_llm_selector("primary", provider="openai").model_name == "GPT-5.5"


def test_chat_api_without_provider_uses_the_switch(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from src.api.server import app
    from src.db import init_db

    db_file = tmp_path / "switch.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    seen = {}

    def fake_invoke(state, *args, **kwargs):
        seen.update(provider=state["provider"], model=state["model_name"], secondary=state["secondary_model_name"])
        return {"messages": [], "loop_events": []}

    monkeypatch.setattr("src.api.server.agent_app.invoke", fake_invoke)
    TestClient(app).post("/api/chat", json={"message": "hello", "session_id": "switch-test"})

    assert seen == {"provider": "gemini", "model": "gemini-3.8-flash", "secondary": "gemini-3.5-flash-lite"}


def test_retired_gemini_names_map_to_live_models(monkeypatch):
    captured = {}

    class FakeChat:
        def __init__(self, model, temperature, google_api_key):
            captured["model"] = model

    import langchain_google_genai

    monkeypatch.setattr(langchain_google_genai, "ChatGoogleGenerativeAI", FakeChat)
    monkeypatch.setenv("GOOGLE_API_KEY", "g-key")

    get_model_instance("gemini", "gemini-1.5-flash")
    assert captured["model"] == "gemini-3.5-flash-lite"
    get_model_instance("gemini", "gemini-3.8-flash")
    assert captured["model"] == "gemini-3.8-flash"


@pytest.mark.parametrize(
    "endpoint,expected",
    [
        ("https://generativelanguage.googleapis.com/v1beta/openai", "google-key"),
        ("https://api.openai.com/v1", "openai-key"),
        ("https://opencode.ai/zen/v1", "not-required"),
    ],
)
def test_jev_key_follows_its_endpoint(monkeypatch, endpoint, expected):
    from src.memory.jev import _jev_api_key

    monkeypatch.delenv("JEV_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "google-key")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")

    assert _jev_api_key(endpoint) == expected
    monkeypatch.setenv("JEV_API_KEY", "explicit")
    assert _jev_api_key(endpoint) == "explicit"


@pytest.mark.parametrize(
    "env,expected",
    [
        ({"AI_PROVIDER": "gemini", "PRIMARY_MODEL": "GPT-5.5"}, ("gemini", "gemini-3.8-flash")),
        ({"AI_PROVIDER": "gemini", "PRIMARY_PROVIDER": "openai"}, ("openai", "GPT-5.5")),
        ({"AI_PROVIDER": "gemini", "PRIMARY_MODEL": "gemini-3.7-flash"}, ("gemini", "gemini-3.7-flash")),
        ({"PRIMARY_MODEL": "GPT-5.5"}, ("openai", "GPT-5.5")),
        ({"PRIMARY_PROVIDER": "openai", "PRIMARY_MODEL": "gpt-5.1-custom"}, ("openai", "gpt-5.1-custom")),
    ],
)
def test_model_overrides_never_pair_a_model_with_the_wrong_provider(env, expected):
    cfg = load_memory_config(environ=env)

    assert (cfg.primary_llm.provider, cfg.primary_llm.model_name) == expected
