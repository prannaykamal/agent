import pytest
from fastapi.testclient import TestClient
from src.api.server import app
from src.harness.state import AgentState
from src.memory.short_term import generate_thread_title

client = TestClient(app)

def test_agent_state_has_secondary_model_fields():
    """Verifies AgentState schema includes secondary_provider and secondary_model_name."""
    annotations = AgentState.__annotations__
    assert "secondary_provider" in annotations
    assert "secondary_model_name" in annotations

def test_generate_thread_title_accepts_secondary_model_params():
    """Verifies generate_thread_title accepts secondary provider and model parameters."""
    title = generate_thread_title(
        "Refactor database migration script for user profiles",
        secondary_provider="anthropic",
        secondary_model_name="claude-3-5-haiku-latest"
    )
    assert isinstance(title, str)
    assert len(title) > 0
    assert title != "New Chat"

def test_post_chat_accepts_dual_llm_selectors():
    """Verifies POST /api/chat accepts primary and secondary LLM provider & model fields."""
    res = client.post("/api/chat", json={
        "message": "Plan a weekly sprint review",
        "session_id": "new_thread_dual_llm_test_99",
        "provider": "openai",
        "model_name": "gpt-4o",
        "secondary_provider": "anthropic",
        "secondary_model_name": "claude-3-5-haiku-latest"
    })
    assert res.status_code == 200
    data = res.json()
    assert "session_id" in data
    assert "response" in data
