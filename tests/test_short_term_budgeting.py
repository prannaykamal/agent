import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from src.db import init_db
from src.memory.short_term import (
    get_compaction_ratio,
    log_raw_turn,
    get_raw_turns,
    manage_short_term_memory_with_budget,
    estimate_tokens
)
from src.api.server import app

@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_budget.db"
    mem_file = tmp_path / "MEMORY.md"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    monkeypatch.setattr("src.config.MEMORY_PATH", mem_file)
    init_db(db_file)
    return db_file

client = TestClient(app)

def test_compaction_ratios():
    assert get_compaction_ratio(128000) == 0.30
    assert get_compaction_ratio(200000) == 0.30
    assert get_compaction_ratio(400000) == 0.25
    assert get_compaction_ratio(1000000) == 0.20

def test_raw_turns_logging_and_retrieval(temp_db):
    turn1 = log_raw_turn("session_abc", "user", "What is Python?", db_path=temp_db)
    turn2 = log_raw_turn("session_abc", "assistant", "Python is a programming language.", db_path=temp_db)

    assert turn1.startswith("turn_")
    assert turn2.startswith("turn_")

    turns = get_raw_turns("session_abc", db_path=temp_db)
    assert len(turns) == 2
    assert turns[0]["sender"] == "user"
    assert turns[0]["content"] == "What is Python?"
    assert turns[1]["sender"] == "assistant"

def test_legacy_budget_compaction_wrapper_does_not_summarize_synchronously(temp_db):
    messages = [SystemMessage(content="System instruction")]
    for i in range(20):
        messages.append(HumanMessage(content=f"User message turn #{i} with substantial token padding text " * 10))
        messages.append(AIMessage(content=f"AI response turn #{i} with substantial token padding text " * 10))

    returned, summary = manage_short_term_memory_with_budget(
        messages=messages,
        existing_summary="",
        context_window_limit=500,
        provider="openai"
    )

    assert returned is messages
    assert summary == ""
    assert not any("[Short-Term Memory Compacted Summary]" in str(m.content) for m in returned)

def test_api_history_endpoint(temp_db):
    client.post("/api/chat", json={"message": "First hello turn", "session_id": "sess_hist_123"})
    client.post("/api/chat", json={"message": "Second question turn", "session_id": "sess_hist_123"})

    resp = client.get("/api/history/sess_hist_123")
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == "sess_hist_123"
    assert data["total_turns"] >= 2
