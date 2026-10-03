import json
import sqlite3
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from src.api.server import app
from src.db import init_db
from src.memory.cognee_memory import get_cognee_memory
from src.memory.observability import redact_observability_payload

client = TestClient(app)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "phase11_observability.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file


TABLES = [
    "memory_jobs",
    "dead_letter_jobs",
    "worker_heartbeats",
    "raw_turns",
    "summary_blocks",
    "approval_requests",
]


def _counts(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in TABLES}
    finally:
        conn.close()


def _execute(db_path, sql, params=()):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


def _seed_observability_rows(db_path):
    payload = {"message_text": "private deployment conversation", "api_key": "sk-secret", "chain_of_thought": "hidden"}
    _execute(
        db_path,
        """
        INSERT INTO memory_jobs (id, job_type, status, priority, session_id, idempotency_key, payload_json)
        VALUES ('job-obs', 'cognee_ingest', 'QUEUED', 10, 'phase11', 'idem-obs', ?)
        """,
        (json.dumps(payload),),
    )
    _execute(
        db_path,
        """
        INSERT INTO dead_letter_jobs (id, job_id, job_type, session_id, payload_json, last_error, error_details_json, attempt_count)
        VALUES ('dlj-obs', 'job-dead', 'summary_generation', 'phase11', '{}', 'failed', ?, 3)
        """,
        (json.dumps({"authorization": "Bearer abc", "prompt": "full private prompt"}),),
    )
    old = (datetime.utcnow() - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
    _execute(
        db_path,
        """
        INSERT INTO worker_heartbeats (worker_id, worker_type, status, last_heartbeat_at, started_at, metadata_json)
        VALUES ('worker-obs', 'memory', 'IDLE', ?, ?, '{}')
        """,
        (old, old),
    )


def _teach(text):
    get_cognee_memory().remember_permanent([text])


def test_observability_endpoints_are_read_only_and_report_subsystems(temp_db, fake_cognee):
    _teach("Fact about the user (profile): User prefers observability")
    _seed_observability_rows(temp_db)
    before = _counts(temp_db)
    graph_before = (len(fake_cognee.remember_calls), len(fake_cognee.improve_calls))

    endpoints = [
        ("GET", "/api/memory/observability/health"),
        ("GET", "/api/memory/observability/jobs?include_payload=true"),
        ("GET", "/api/memory/observability/workers?stale_after_seconds=1"),
        ("GET", "/api/memory/observability/dead-letter?include_details=true"),
        ("POST", "/api/memory/observability/retrieval/trace"),
        ("GET", "/api/memory/observability/long-term"),
        ("GET", "/api/memory/observability/overview"),
    ]
    responses = []
    for method, url in endpoints:
        if method == "POST":
            responses.append(client.post(url, json={"query": "what observability preference do I have?", "session_id": "phase11"}))
        else:
            responses.append(client.get(url))

    assert all(response.status_code == 200 for response in responses)
    health = responses[0].json()
    assert {"schema", "queue", "workers", "long_term"} <= set(health)
    assert health["long_term"]["available"] is True
    assert health["long_term"]["pipeline"]["cognee_ingest"]["by_status"] == {"QUEUED": 1}
    trace = responses[4].json()
    assert trace["candidate_count"] == 1
    assert "observability" in trace["candidates"][0]["content_preview"]
    assert _counts(temp_db) == before
    assert (len(fake_cognee.remember_calls), len(fake_cognee.improve_calls)) == graph_before


def test_jobs_dead_letter_and_trace_redact_payloads(temp_db, fake_cognee):
    _teach("Fact about the user (profile): User prefers redaction")
    _seed_observability_rows(temp_db)

    jobs = client.get("/api/memory/observability/jobs?include_payload=true").json()["jobs"][0]
    dead = client.get("/api/memory/observability/dead-letter?include_details=true").json()["dead_letters"][0]
    trace = client.post(
        "/api/memory/observability/retrieval/trace",
        json={"query": "what redaction preference do I have?", "session_id": "phase11", "include_prompt_block": True},
    ).json()

    assert jobs["payload"]["api_key"] == "[REDACTED]"
    assert jobs["payload"]["message_text"]["redacted"] is True
    assert jobs["payload"]["chain_of_thought"] == "[REDACTED]"
    assert dead["details"]["authorization"] == "[REDACTED]"
    assert dead["details"]["prompt"]["redacted"] is True
    assert trace["prompt_block"]["redacted"] is True
    assert "api_key" not in json.dumps(trace).lower()


def test_retrieval_trace_creates_no_chat_turn_and_writes_no_memory(temp_db, fake_cognee):
    _teach("Fact about the user (profile): User prefers trace safety")
    before = _counts(temp_db)

    response = client.post(
        "/api/memory/observability/retrieval/trace",
        json={"query": "what trace safety preference do I have?", "session_id": "phase11"},
    )

    assert response.status_code == 200
    assert _counts(temp_db) == before
    assert response.json()["query"] == "what trace safety preference do I have?"


def test_redaction_preserves_safe_fields_and_removes_nested_sensitive_values():
    payload = {
        "job_id": "job-1",
        "status": "QUEUED",
        "api_token": "secret-token",
        "conversation": "very long private conversation",
        "nested": {"password": "pw", "scratchpad": "hidden", "schema_version": 1},
    }

    redacted = redact_observability_payload(payload)

    assert redacted["job_id"] == "job-1"
    assert redacted["status"] == "QUEUED"
    assert redacted["api_token"] == "[REDACTED]"
    assert redacted["conversation"]["redacted"] is True
    assert redacted["nested"]["password"] == "[REDACTED]"
    assert redacted["nested"]["scratchpad"] == "[REDACTED]"
    assert redacted["nested"]["schema_version"] == 1


def test_health_is_degraded_when_cognee_is_unavailable(temp_db):
    health = client.get("/api/memory/observability/health").json()

    assert health["status"] == "DEGRADED"
    assert health["long_term"]["available"] is False
    assert "disabled" in health["long_term"]["error"]
