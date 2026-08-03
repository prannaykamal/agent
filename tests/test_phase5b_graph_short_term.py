import sqlite3

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import HumanMessage, SystemMessage

from src.api.server import app
from src.db import init_db
from src.harness.graph import node_manage_memory
from src.memory.summary_blocks import SUMMARY_PENDING_NOTICE, SummaryBlockRepository
from src.memory.token_budget import ConversationTokenBudget


client = TestClient(app)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "phase5b_graph.db"
    mem_file = tmp_path / "MEMORY.md"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    monkeypatch.setattr("src.config.MEMORY_PATH", mem_file)
    init_db(db_file)
    return db_file


def _insert_turn(db_path, turn_id, sender, content, tokens=10, session_id="sess"):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO raw_turns (id, session_id, sender, content, tokens, created_at) VALUES (?, ?, ?, ?, ?, datetime('now'))",
            (turn_id, session_id, sender, content, tokens),
        )
        conn.commit()
    finally:
        conn.close()


def _jobs(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in conn.execute("SELECT * FROM memory_jobs ORDER BY rowid ASC").fetchall()]
    finally:
        conn.close()


def _budget(trigger=False, historical=10, conversation_budget=1000, context_window=128000):
    return ConversationTokenBudget(
        provider="openai",
        model_name="gpt-4o-mini",
        context_window=context_window,
        conversation_budget_tokens=conversation_budget,
        summarization_trigger_tokens=int(conversation_budget * 0.9),
        historical_conversation_tokens=historical,
        current_user_message_tokens=1,
        system_prompt_tokens=1,
        tool_schema_tokens=0,
        retrieved_memory_tokens=0,
        output_reserve_tokens=10,
        safety_margin_tokens=5,
        reserved_tokens=16,
        available_input_tokens=context_window - 15,
        budget_usage_ratio=historical / conversation_budget if conversation_budget else 1.0,
        trigger_usage_ratio=1.0 if trigger else 0.1,
        should_trigger_summarization=trigger,
        counter_uses_fallback=True,
    )


def test_node_manage_memory_does_not_call_secondary_route_or_llm(temp_db, monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("secondary route/LLM must not be called in node_manage_memory")

    monkeypatch.setattr("src.harness.llm_router.resolve_secondary_llm", fail)
    monkeypatch.setattr("src.harness.models.get_secondary_llm", fail)
    monkeypatch.setattr("src.memory.summary_blocks.calculate_budget_for_primary_route", lambda **kwargs: _budget(False))

    result = node_manage_memory(
        {
            "messages": [SystemMessage(content="system"), HumanMessage(content="hello")],
            "session_id": "sess",
            "provider": "openai",
            "model_name": "gpt-4o-mini",
        }
    )

    assert result["summary_status"] == "WITHIN_BUDGET"
    assert result["pending_summary_job_id"] is None


def test_over_budget_node_manage_memory_enqueues_summary_generation(temp_db, monkeypatch):
    _insert_turn(temp_db, "t1", "user", "old user", 100)
    _insert_turn(temp_db, "t2", "assistant", "old assistant", 100)
    _insert_turn(temp_db, "t3", "user", "current", 10)
    monkeypatch.setattr(
        "src.memory.summary_blocks.calculate_budget_for_primary_route",
        lambda **kwargs: _budget(True, historical=200, conversation_budget=150),
    )

    result = node_manage_memory(
        {
            "messages": [SystemMessage(content="system"), HumanMessage(content="current")],
            "session_id": "sess",
            "provider": "openai",
            "model_name": "gpt-4o-mini",
            "secondary_provider": "anthropic",
            "secondary_model_name": "claude-3-5-haiku-latest",
        }
    )
    jobs = _jobs(temp_db)

    assert result["summary_status"] == "SUMMARY_PENDING"
    assert result["pending_summary_job_id"]
    assert len(jobs) == 1
    assert jobs[0]["job_type"] == "summary_generation"
    assert jobs[0]["priority"] == 50
    payload = __import__("json").loads(jobs[0]["payload_json"])
    assert payload["summary_generation"]["selected_turn_ids"] == ["t1"]
    assert "semantic" not in payload
    assert "episodic" not in payload
    assert "procedural" not in payload


def test_below_threshold_enqueues_no_summary_job(temp_db, monkeypatch):
    _insert_turn(temp_db, "t1", "user", "old", 10)
    _insert_turn(temp_db, "t2", "user", "current", 10)
    monkeypatch.setattr("src.memory.summary_blocks.calculate_budget_for_primary_route", lambda **kwargs: _budget(False))

    node_manage_memory(
        {
            "messages": [SystemMessage(content="system"), HumanMessage(content="current")],
            "session_id": "sess",
            "provider": "openai",
            "model_name": "gpt-4o-mini",
        }
    )

    assert _jobs(temp_db) == []


def test_duplicate_summary_job_is_reused(temp_db, monkeypatch):
    _insert_turn(temp_db, "t1", "user", "old user", 100)
    _insert_turn(temp_db, "t2", "assistant", "old assistant", 100)
    _insert_turn(temp_db, "t3", "user", "current", 10)
    monkeypatch.setattr(
        "src.memory.summary_blocks.calculate_budget_for_primary_route",
        lambda **kwargs: _budget(True, historical=200, conversation_budget=150),
    )
    state = {
        "messages": [SystemMessage(content="system"), HumanMessage(content="current")],
        "session_id": "sess",
        "provider": "openai",
        "model_name": "gpt-4o-mini",
        "secondary_provider": "openai",
        "secondary_model_name": "gpt-4o-mini",
    }

    first = node_manage_memory(state)
    second = node_manage_memory(state)

    assert first["pending_summary_job_id"] == second["pending_summary_job_id"]
    assert len(_jobs(temp_db)) == 1


def test_pending_summary_uses_notice_and_current_user_once(temp_db, monkeypatch):
    _insert_turn(temp_db, "t1", "user", "old user", 100)
    _insert_turn(temp_db, "t2", "assistant", "old assistant", 100)
    _insert_turn(temp_db, "t3", "user", "current", 10)
    monkeypatch.setattr(
        "src.memory.summary_blocks.calculate_budget_for_primary_route",
        lambda **kwargs: _budget(True, historical=200, conversation_budget=100),
    )

    result = node_manage_memory(
        {
            "messages": [SystemMessage(content="system"), HumanMessage(content="current")],
            "session_id": "sess",
            "provider": "openai",
            "model_name": "gpt-4o-mini",
        }
    )
    contents = [str(message.content) for message in result["messages"]]

    assert any(SUMMARY_PENDING_NOTICE in content for content in contents)
    assert sum(content == "current" for content in contents) == 1
    assert result["trimming_occurred"] is True


def test_completed_summary_blocks_are_used_and_covered_raw_turns_omitted(temp_db, monkeypatch):
    _insert_turn(temp_db, "t1", "user", "covered raw", 50)
    _insert_turn(temp_db, "t2", "assistant", "recent raw", 50)
    _insert_turn(temp_db, "t3", "user", "current", 10)
    SummaryBlockRepository(db_path=temp_db).append_summary_block(
        session_id="sess",
        summary="Covered summary",
        covered_message_ids=["t1"],
        start_message_id="t1",
        end_message_id="t1",
        source_job_id="job-done",
        token_count=4,
        original_token_count=50,
        model_provider="openai",
        model_name="gpt-4o-mini",
    )
    monkeypatch.setattr("src.memory.summary_blocks.calculate_budget_for_primary_route", lambda **kwargs: _budget(False))

    result = node_manage_memory(
        {
            "messages": [SystemMessage(content="system"), HumanMessage(content="current")],
            "session_id": "sess",
            "provider": "openai",
            "model_name": "gpt-4o-mini",
        }
    )
    contents = "\n".join(str(message.content) for message in result["messages"])

    assert "Covered summary" in contents
    assert "covered raw" not in contents
    assert "recent raw" in contents
    assert result["summary_status"] == "SUMMARY_AVAILABLE"


def test_chat_response_shape_remains_unchanged(temp_db):
    response = client.post(
        "/api/chat",
        json={"message": "Hello shape", "session_id": "phase5b_shape"},
    )

    assert response.status_code == 200
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
    ).issubset(response.json().keys())
