import json
import sqlite3
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from src.api.server import app
from src.db import init_db

client = TestClient(app)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "phase10_observability.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file


def _execute(db_path, sql, params=()):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


def test_health_endpoint_top_level_keys_and_required_tables(temp_db):
    resp = client.get("/api/memory/observability/health")

    assert resp.status_code == 200
    data = resp.json()
    assert {"status", "generated_at", "schema", "queue", "workers", "long_term"} <= set(data)
    assert data["schema"]["required_tables_present"] is True
    assert data["schema"]["missing_tables"] == []


def test_health_degraded_when_dead_letters_exist(temp_db):
    _execute(
        temp_db,
        """
        INSERT INTO dead_letter_jobs (id, job_id, job_type, session_id, payload_json, last_error, attempt_count)
        VALUES ('dlj-1', 'job-1', 'cognee_cognify', 'sess', '{}', 'failed with secret token abc', 3)
        """,
    )

    resp = client.get("/api/memory/observability/health")

    assert resp.status_code == 200
    assert resp.json()["status"] == "DEGRADED"
    assert resp.json()["queue"]["dead_letter_count"] == 1


def test_jobs_summary_filters_and_payload_redaction(temp_db):
    payload = {"schema_version": 1, "message_text": "User said a private thing", "api_key": "sk-secret"}
    _execute(
        temp_db,
        """
        INSERT INTO memory_jobs (id, job_type, status, priority, session_id, idempotency_key, payload_json)
        VALUES ('job-1', 'semantic_candidate_extraction', 'QUEUED', 10, 'sess-a', 'idem-1', ?)
        """,
        (json.dumps(payload),),
    )
    _execute(
        temp_db,
        """
        INSERT INTO memory_jobs (id, job_type, status, priority, session_id, idempotency_key, payload_json)
        VALUES ('job-2', 'summary_generation', 'SUCCEEDED', 20, 'sess-b', 'idem-2', '{}')
        """,
    )

    default_resp = client.get("/api/memory/observability/jobs?session_id=sess-a")
    payload_resp = client.get("/api/memory/observability/jobs?session_id=sess-a&include_payload=true")

    assert default_resp.status_code == 200
    assert default_resp.json()["summary"]["total"] == 1
    assert default_resp.json()["jobs"][0]["payload"] is None
    redacted = payload_resp.json()["jobs"][0]["payload"]
    assert redacted["api_key"] == "[REDACTED]"
    assert redacted["message_text"]["redacted"] is True
    assert "private thing" in redacted["message_text"]["preview"]


def test_workers_empty_and_stale_heartbeat(temp_db):
    empty = client.get("/api/memory/observability/workers")
    assert empty.status_code == 200
    assert empty.json()["summary"]["total"] == 0

    old_time = (datetime.utcnow() - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
    _execute(
        temp_db,
        """
        INSERT INTO worker_heartbeats (worker_id, worker_type, status, last_heartbeat_at, started_at, metadata_json)
        VALUES ('worker-1', 'memory', 'IDLE', ?, ?, ?)
        """,
        (old_time, old_time, json.dumps({"hostname": "host", "pid": 123, "worker_version": 1})),
    )

    stale = client.get("/api/memory/observability/workers?stale_after_seconds=1")
    worker = stale.json()["workers"][0]
    assert worker["stale"] is True
    assert "hostname" not in worker["metadata"]
    assert "pid" not in worker["metadata"]


def test_dead_letter_redaction(temp_db):
    details = {"prompt": "full private prompt text", "authorization": "Bearer abc"}
    _execute(
        temp_db,
        """
        INSERT INTO dead_letter_jobs (id, job_id, job_type, session_id, payload_json, last_error, error_details_json, attempt_count)
        VALUES ('dlj-1', 'job-1', 'semantic_consolidation', 'sess', '{}', 'bad failure', ?, 3)
        """,
        (json.dumps(details),),
    )

    default_resp = client.get("/api/memory/observability/dead-letter")
    detail_resp = client.get("/api/memory/observability/dead-letter?include_details=true")

    assert default_resp.json()["dead_letters"][0]["details"] is None
    details = detail_resp.json()["dead_letters"][0]["details"]
    assert details["authorization"] == "[REDACTED]"
    assert details["prompt"]["redacted"] is True


def _jobs(db_path, job_type):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in conn.execute("SELECT * FROM memory_jobs WHERE job_type = ?", (job_type,))]
    finally:
        conn.close()


def test_fact_and_procedure_endpoints_queue_permanent_cognee_ingest(temp_db):
    fact = client.post("/api/memory/fact", json={"category": "ui", "fact_text": "User likes compact UI"})
    duplicate = client.post("/api/memory/fact", json={"category": "ui", "fact_text": "User likes compact UI"})
    procedure = client.post(
        "/api/memory/procedure",
        json={"name": "Inbox digest", "description": "Summarize mail", "trigger_keywords": "inbox", "execution_steps": "1. Fetch 2. Summarize"},
    )

    assert fact.status_code == duplicate.status_code == procedure.status_code == 200
    assert fact.json()["status"] == "queued" and fact.json()["inserted"] is True
    assert duplicate.json()["inserted"] is False
    documents = [json.loads(job["payload_json"])["documents"][0] for job in _jobs(temp_db, "cognee_ingest")]
    assert "Fact about the user (ui): User likes compact UI" in documents
    assert any("Use when: inbox" in doc for doc in documents)
    # Explicit writes skip the session cache and Jev entirely.
    assert _jobs(temp_db, "memory_session_write") == []


def test_memory_write_endpoints_validate_input(temp_db):
    assert client.post("/api/memory/fact", json={"category": "ui", "fact_text": "  "}).status_code == 400
    assert client.post("/api/memory/procedure", json={"name": "x", "description": "", "execution_steps": " "}).status_code == 400
    assert client.post("/api/memory/search", json={"query": " "}).status_code == 400
    assert client.post("/api/memory/search", json={"query": "q", "search_type": "CYPHER"}).status_code == 400
    assert _jobs(temp_db, "cognee_ingest") == []


def test_search_endpoint_returns_recalled_memories(temp_db, fake_cognee):
    from src.memory.cognee_memory import get_cognee_memory

    get_cognee_memory().remember_permanent(["Fact about the user (ui): User likes compact layouts"])

    data = client.post("/api/memory/search", json={"query": "compact layouts?", "top_k": 500}).json()

    assert data["available"] is True
    assert [item["content"] for item in data["memories"]] == ["Fact about the user (ui): User likes compact layouts"]
    assert fake_cognee.search_calls[-1]["top_k"] == 50


def test_merge_endpoint_queues_forced_merge_and_long_term_reports_it(temp_db):
    first = client.post("/api/memory/sessions/s1/merge").json()
    long_term = client.get("/api/memory/observability/long-term").json()

    assert first["status"] == "queued" and first["inserted"] is True
    [job] = _jobs(temp_db, "memory_session_merge")
    assert json.loads(job["payload_json"])["force"] is True
    assert long_term["backend"] == "cognee"
    assert long_term["available"] is False
    assert long_term["pipeline"]["memory_session_merge"]["by_status"] == {"QUEUED": 1}
    assert long_term["jev"] == {"configured": False, "model": None, "tool_review_enabled": True}
    assert client.post("/api/memory/cognify").status_code in (404, 405)


def test_removed_store_endpoints_are_gone(temp_db):
    assert client.get("/api/memory/observability/semantic").status_code == 404
    assert client.get("/api/memory/observability/procedural").status_code == 404
    assert client.get("/api/memory/observability/skills").status_code == 404
    assert client.get("/api/skills").status_code == 404
