import sqlite3

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.db import init_db
from src.harness.graph import agent_app, node_consolidate


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "phase3a_graph.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file


def _count_rows(db_path, table_name):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
    finally:
        conn.close()


def _memory_jobs(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT * FROM memory_jobs ORDER BY rowid ASC").fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


@pytest.fixture(autouse=True)
def _cognee_enabled(fake_cognee):
    return fake_cognee


def _completed_state(approval_status="NONE", should_store=True):
    return {
        "messages": [
            HumanMessage(content="Remember that I prefer careful migrations."),
            AIMessage(content="I will keep migrations careful and additive."),
        ],
        "session_id": "phase3a-graph",
        "summary": "",
        "token_count": 9,
        "retrieval_triggered": False,
        "retrieved_memories": [],
        "pending_approval_id": None,
        "approval_status": approval_status,
        "provider": "openai",
        "model_name": "gpt-4o-mini",
        "secondary_provider": "openai",
        "secondary_model_name": "gpt-4o-mini",
        "tools_used": [],
        "loop_count": 1,
        "loop_events": [],
        "memory_storage_decision": {"should_store": should_store, "source": "jev"},
    }


def test_node_consolidate_enqueues_session_write_job(temp_db):
    result = node_consolidate(_completed_state())
    jobs = _memory_jobs(temp_db)

    assert len(jobs) >= 1
    assert jobs[0]["job_type"] == "memory_session_write"
    assert jobs[0]["status"] == "QUEUED"
    assert jobs[0]["session_id"] == "phase3a-graph"
    assert jobs[0]["result_json"] is None
    assert jobs[0]["error_message"] is None
    assert jobs[0]["locked_by"] is None
    assert jobs[0]["started_at"] is None
    assert result["memory_job_ids"][0] == jobs[0]["id"]


def test_successful_graph_turn_stores_only_when_jev_says_so(temp_db, fake_jev):
    state = {
        "messages": [HumanMessage(content="Remember that I prefer careful migrations.")],
        "session_id": "phase3a-agent",
        "summary": "",
        "token_count": 0,
        "retrieval_triggered": False,
        "retrieved_memories": [],
        "pending_approval_id": None,
        "approval_status": None,
        "provider": "openai",
        "model_name": "gpt-4o-mini",
    }

    fake_jev.memory = {"should_store": False, "should_retrieve": False}
    agent_app.invoke(state)
    assert _memory_jobs(temp_db) == []

    fake_jev.memory = {"should_store": True, "should_retrieve": False}
    result = agent_app.invoke({**state, "session_id": "phase3a-agent-2"})
    jobs = _memory_jobs(temp_db)

    assert result.get("memory_job_ids")
    assert [job["job_type"] for job in jobs] == ["memory_session_write"]
    assert all(job["status"] == "QUEUED" for job in jobs)


def test_turn_not_worth_storing_enqueues_no_job(temp_db):
    result = node_consolidate(_completed_state(should_store=False))

    assert result == {"memory_job_ids": []}
    assert _count_rows(temp_db, "memory_jobs") == 0


def test_hitl_pending_enqueues_no_job(temp_db):
    result = node_consolidate(_completed_state(approval_status="PENDING"))

    assert result == {"memory_job_ids": []}
    assert _count_rows(temp_db, "memory_jobs") == 0


def test_hitl_rejected_enqueues_no_job(temp_db):
    result = node_consolidate(_completed_state(approval_status="REJECTED"))

    assert result == {"memory_job_ids": []}
    assert _count_rows(temp_db, "memory_jobs") == 0


def test_node_consolidate_does_not_call_cognee_inline(temp_db, fake_cognee):

    result = node_consolidate(_completed_state())

    assert result["memory_job_ids"]
    assert fake_cognee.remember_calls == []
    assert fake_cognee.improve_calls == []


def test_node_consolidate_does_not_call_get_secondary_llm(temp_db, monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("secondary LLM must not be called for memory enqueue")

    monkeypatch.setattr("src.harness.models.get_secondary_llm", fail)

    result = node_consolidate(_completed_state())

    assert result["memory_job_ids"]


def test_duplicate_node_consolidate_reuses_existing_row(temp_db):
    first = node_consolidate(_completed_state())
    second = node_consolidate(_completed_state())

    assert first["memory_job_ids"] == second["memory_job_ids"]
    assert _count_rows(temp_db, "memory_jobs") == len(first["memory_job_ids"])


def test_enqueue_failure_does_not_break_consolidate_response(temp_db, monkeypatch):
    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr("src.harness.graph.enqueue_post_turn_memory_jobs", fail)

    result = node_consolidate(_completed_state())

    assert result == {"memory_job_ids": []}


def test_phase3a_consolidation_only_writes_to_memory_jobs(temp_db):
    untouched_tables = [
        "dead_letter_jobs",
        "worker_heartbeats",
        "pending_fact_candidates",
        "structured_episodes",
        "facts",
        "episodes",
    ]
    before = {table: _count_rows(temp_db, table) for table in untouched_tables}

    node_consolidate(_completed_state())

    assert _count_rows(temp_db, "memory_jobs") >= 1
    after = {table: _count_rows(temp_db, table) for table in untouched_tables}
    assert after == before
