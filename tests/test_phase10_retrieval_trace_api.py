import sqlite3

import pytest
from fastapi.testclient import TestClient

from src.api.server import app
from src.db import add_fact, init_db

client = TestClient(app)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "phase10_trace.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file


def _count(db_path, table):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def test_retrieval_trace_requires_non_empty_query(temp_db):
    resp = client.post("/api/memory/observability/retrieval/trace", json={"query": "   "})

    assert resp.status_code == 400
    assert "query" in resp.json()["detail"]


def test_greeting_and_math_gate_skipped(temp_db):
    greeting = client.post("/api/memory/observability/retrieval/trace", json={"query": "hello"})
    math = client.post("/api/memory/observability/retrieval/trace", json={"query": "2 + 2"})

    assert greeting.status_code == 200
    assert greeting.json()["gate"]["allowed"] is False
    assert greeting.json()["retrieval"]["candidate_count"] == 0
    assert math.json()["gate"]["allowed"] is False


def test_trace_returns_planner_task_type_source_counts_and_hides_prompt_by_default(temp_db):
    add_fact("profile", "User prefers pytest for test automation", db_path=temp_db)

    resp = client.post(
        "/api/memory/observability/retrieval/trace",
        json={"query": "what is my preference for pytest?", "session_id": "sess"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["gate"]["allowed"] is True
    assert data["plan"]["task_type"] == "identity_or_preference"
    assert "semantic" in data["plan"]["memory_kinds"]
    assert data["retrieval"]["source_results"]
    assert data["assembly"]["prompt_block"] is None
    assert data["candidates"]


def test_include_prompt_block_returns_redacted_block(temp_db):
    add_fact("profile", "User prefers FastAPI for backend services", db_path=temp_db)

    resp = client.post(
        "/api/memory/observability/retrieval/trace",
        json={"query": "what is my FastAPI preference?", "include_prompt_block": True},
    )

    block = resp.json()["assembly"]["prompt_block"]
    assert block["redacted"] is True
    assert "preview" in block
    assert "[Retrieved Long-Term Memory]" in block["preview"]


def test_trace_does_not_call_llms_or_write_memory(temp_db, monkeypatch):
    add_fact("profile", "User prefers pytest", db_path=temp_db)

    def fail(*args, **kwargs):
        raise AssertionError("trace must not call LLMs or write helpers")

    monkeypatch.setattr("src.harness.llm_router.resolve_primary_llm", fail)
    monkeypatch.setattr("src.harness.llm_router.resolve_secondary_llm", fail)
    monkeypatch.setattr("src.memory.embeddings.SemanticEmbeddingStore.upsert_embedding", fail)
    monkeypatch.setattr("src.memory.skill_store.SkillVersionStore.record_used", fail)

    before = {table: _count(temp_db, table) for table in ["semantic_embeddings", "semantic_dedup_events", "skill_usage_stats", "memory_jobs", "pending_fact_candidates", "raw_turns"]}

    resp = client.post(
        "/api/memory/observability/retrieval/trace",
        json={"query": "what is my preference for pytest?", "session_id": "sess"},
    )

    assert resp.status_code == 200
    after = {table: _count(temp_db, table) for table in before}
    assert after == before
