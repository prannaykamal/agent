import pytest
from fastapi.testclient import TestClient
from src.api.server import app
from src.memory.short_term import generate_thread_title

client = TestClient(app)

def test_api_models_returns_provider_catalog():
    """Verifies GET /api/models returns providers, pairs, and model options."""
    res = client.get("/api/models")
    assert res.status_code == 200
    data = res.json()
    assert "catalog" in data
    catalog = data["catalog"]
    assert "providers" in catalog
    assert "openai" in catalog["providers"]
    assert "anthropic" in catalog["providers"]
    assert "gemini" in catalog["providers"]
    assert "grok" in catalog["providers"]

def test_generate_thread_title_helper():
    """Verifies generate_thread_title creates a concise topic title."""
    title = generate_thread_title("How do I debug Python async worker queue deadlock?")
    assert isinstance(title, str)
    assert len(title) > 0
    assert title != "New Chat"

def test_chat_first_turn_auto_renames_thread(monkeypatch):
    """Verifies first message in a thread automatically updates session_id to a concise topic title."""
    sess_id = "new_thread_first_turn_test_123"


    res = client.post("/api/chat", json={
        "message": "Create a budget plan for Q3 team lunch",
        "session_id": sess_id,
        "provider": "openai",
        "model_name": "gpt-4o-mini"
    })
    assert res.status_code == 200
    data = res.json()
    assert "session_id" in data
    assert "response" in data
    # The session_id should no longer be the raw temp sess_id, but the concise topic title
    assert data["session_id"] != sess_id
    assert "Q3" in data["session_id"] or "Budget" in data["session_id"] or "Create" in data["session_id"]
