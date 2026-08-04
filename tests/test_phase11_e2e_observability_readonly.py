import json
import sqlite3
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from src.api.server import app
from src.db import add_fact, init_db
from src.memory.observability import redact_observability_payload

client = TestClient(app)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "phase11_observability.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    monkeypatch.setattr("src.config.MEMORY_PATH", tmp_path / "MEMORY.md")
    init_db(db_file)
    return db_file


TABLES = [
    "memory_jobs",
    "dead_letter_jobs",
    "worker_heartbeats",
    "raw_turns",
    "summary_blocks",
    "structured_episodes",
    "pending_fact_candidates",
    "facts",
    "semantic_embeddings",
    "semantic_dedup_events",
    "consolidation_runs",
    "skill_candidates",
    "skill_versions",
    "skill_usage_stats",
    "procedural_skill_approvals",
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
        VALUES ('job-obs', 'semantic_candidate_extraction', 'QUEUED', 10, 'phase11', 'idem-obs', ?)
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
    _execute(
        db_path,
        """
        INSERT INTO pending_fact_candidates (id, session_id, fact, category, confidence, explicit, source, status)
        VALUES ('factcand-obs', 'phase11', 'User likes tests', 'preference', 0.8, 0, 'test', 'PENDING')
        """,
    )
    _execute(
        db_path,
        """
        INSERT INTO skill_candidates (id, title, description, trigger_description, workflow_json, preferred_tools_json, tags_json, confidence, occurrences, source_episode_ids_json, status)
        VALUES ('skillcand-obs', 'Deploy', 'Deploy flow', 'deploy', '[]', '[]', '[]', 0.95, 3, '[]', 'READY_FOR_PROMOTION')
        """,
    )


def test_observability_endpoints_are_read_only_and_report_subsystems(temp_db):
    add_fact("profile", "User prefers observability", db_path=temp_db)
    _seed_observability_rows(temp_db)
    before = _counts(temp_db)

    endpoints = [
        ("GET", "/api/memory/observability/health"),
        ("GET", "/api/memory/observability/jobs?include_payload=true"),
        ("GET", "/api/memory/observability/workers?stale_after_seconds=1"),
        ("GET", "/api/memory/observability/dead-letter?include_details=true"),
        ("POST", "/api/memory/observability/retrieval/trace"),
        ("GET", "/api/memory/observability/semantic"),
        ("GET", "/api/memory/observability/procedural"),
        ("GET", "/api/memory/observability/skills"),
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
    assert {"schema", "queue", "workers", "semantic", "procedural", "skills"} <= set(health)
    assert _counts(temp_db) == before


def test_jobs_dead_letter_and_trace_redact_payloads(temp_db):
    add_fact("profile", "User prefers redaction", db_path=temp_db)
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
    assert "prompt_block" in trace["assembly"]
    assert "api_key" not in json.dumps(trace).lower()


def test_retrieval_trace_creates_no_chat_turn_and_writes_no_memory(temp_db):
    add_fact("profile", "User prefers trace safety", db_path=temp_db)
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


def test_skills_observability_does_not_call_mutating_skill_helpers(temp_db, monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("observability must not mutate skills")

    monkeypatch.setattr("src.memory.skill_reloader.SkillRuntimeReloader.reload_active_skills", fail)
    monkeypatch.setattr("src.memory.skill_reloader.SkillRuntimeReloader.record_skill_used", fail)
    monkeypatch.setattr("src.memory.skill_store.SkillVersionStore.record_used", fail)

    response = client.get("/api/memory/observability/skills")

    assert response.status_code == 200

