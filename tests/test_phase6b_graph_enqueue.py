import sqlite3
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage

from src.api.server import app
from src.db import init_db
from src.harness.graph import node_consolidate


client = TestClient(app)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "phase6b_graph.db"
    mem_file = tmp_path / "MEMORY.md"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    monkeypatch.setattr("src.config.MEMORY_PATH", mem_file)
    init_db(db_file)
    return db_file


def _insert_turn(db_path, turn_id, sender, content, tokens=10, created_at="2026-08-03 10:00:00"):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO raw_turns (id, session_id, sender, content, tokens, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (turn_id, "sess", sender, content, tokens, created_at),
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


def _state(user="Please remember that deploys need approval", assistant="Got it", **overrides):
    state = {
        "messages": [HumanMessage(content=user), AIMessage(content=assistant)],
        "session_id": "sess",
        "provider": "openai",
        "model_name": "gpt-4o-mini",
        "secondary_provider": "openai",
        "secondary_model_name": "gpt-4o-mini",
        "approval_status": "NONE",
        "token_count": 20,
        "retrieval_triggered": False,
        "tools_used": [],
        "loop_count": 1,
    }
    state.update(overrides)
    return state


def test_node_consolidate_enqueues_episode_for_explicit_remember(temp_db):
    _insert_turn(temp_db, "t1", "user", "Please remember that deploys need approval")
    _insert_turn(temp_db, "t2", "assistant", "Got it")

    result = node_consolidate(_state())
    jobs = _jobs(temp_db)

    assert len(result["memory_job_ids"]) == 2
    assert [job["job_type"] for job in jobs] == ["semantic_candidate_extraction", "episode_generation"]


@pytest.mark.parametrize("flag", ["task_completed", "workflow_finished", "trimming_occurred"])
def test_node_consolidate_enqueues_episode_for_completion_and_trimming(temp_db, flag):
    _insert_turn(temp_db, "t1", "user", "Finish this")
    _insert_turn(temp_db, "t2", "assistant", "Done")

    node_consolidate(_state(user="Finish this", assistant="Done", **{flag: True}))
    jobs = _jobs(temp_db)

    assert [job["job_type"] for job in jobs] == ["semantic_candidate_extraction", "episode_generation"]


def test_node_consolidate_enqueues_episode_for_idle_timeout(temp_db):
    previous = datetime(2026, 8, 3, 10, 0, 0)
    latest = previous + timedelta(seconds=2700)
    _insert_turn(temp_db, "t1", "assistant", "Previous", created_at=previous.strftime("%Y-%m-%d %H:%M:%S"))
    _insert_turn(temp_db, "t2", "user", "After pause", created_at=latest.strftime("%Y-%m-%d %H:%M:%S"))
    _insert_turn(temp_db, "t3", "assistant", "Welcome back", created_at=latest.strftime("%Y-%m-%d %H:%M:%S"))

    node_consolidate(_state(user="After pause", assistant="Welcome back"))
    episode_payload = next(job for job in _jobs(temp_db) if job["job_type"] == "episode_generation")["payload_json"]

    assert '"idle_timeout":true' in episode_payload


def test_node_consolidate_enqueues_episode_for_long_conversation(temp_db):
    for index in range(1, 8):
        _insert_turn(temp_db, f"t{index}", "user" if index % 2 else "assistant", f"turn {index}", tokens=10000)

    node_consolidate(_state(user="Current", assistant="OK"))
    episode_payload = next(job for job in _jobs(temp_db) if job["job_type"] == "episode_generation")["payload_json"]

    assert '"long_conversation":true' in episode_payload


def test_node_consolidate_does_not_call_secondary_llm(temp_db, monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("chat path must not call secondary LLM")

    monkeypatch.setattr("src.harness.models.get_secondary_llm", fail)
    monkeypatch.setattr("src.harness.llm_router.resolve_secondary_llm", fail)
    monkeypatch.setattr("src.harness.llm_router.resolve_secondary_from_job_payload", fail)
    _insert_turn(temp_db, "t1", "user", "Please remember that deploys need approval")
    _insert_turn(temp_db, "t2", "assistant", "Got it")

    result = node_consolidate(_state())

    assert len(result["memory_job_ids"]) == 2


def test_chat_response_shape_unchanged(temp_db):
    response = client.post("/api/chat", json={"message": "Hello Phase 6B", "session_id": "phase6b_shape"})

    assert response.status_code == 200
    data = response.json()



