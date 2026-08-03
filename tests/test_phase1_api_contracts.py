from fastapi.testclient import TestClient

from src.api.server import app

client = TestClient(app)


def test_phase1_api_models_keeps_catalog_and_adds_memory_defaults():
    res = client.get("/api/models")

    assert res.status_code == 200
    data = res.json()
    assert "catalog" in data
    assert "providers" in data["catalog"]
    assert "role_defaults" in data["catalog"]
    assert "memory_defaults" in data
    assert data["memory_defaults"]["short_term"]["conversation_budget_ratio"] == 0.75
    assert data["memory_defaults"]["procedural"]["promotion_occurrence_threshold"] == 3


def test_phase1_api_chat_still_accepts_dual_model_selectors():
    res = client.post("/api/chat", json={
        "message": "Check Phase 1 API compatibility",
        "session_id": "phase1_api_compat",
        "provider": "openai",
        "model_name": "gpt-4o-mini",
        "secondary_provider": "anthropic",
        "secondary_model_name": "claude-3-5-haiku-latest",
    })

    assert res.status_code == 200
    data = res.json()
    assert "session_id" in data
    assert "response" in data
