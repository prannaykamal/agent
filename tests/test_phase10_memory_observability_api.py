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
    assert {"status", "generated_at", "schema", "queue", "workers", "semantic", "procedural", "skills"} <= set(data)
    assert data["schema"]["required_tables_present"] is True
    assert data["schema"]["missing_tables"] == []


def test_health_degraded_when_dead_letters_exist(temp_db):
    _execute(
        temp_db,
        """
        INSERT INTO dead_letter_jobs (id, job_id, job_type, session_id, payload_json, last_error, attempt_count)
        VALUES ('dlj-1', 'job-1', 'semantic_consolidation', 'sess', '{}', 'failed with secret token abc', 3)
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


def test_semantic_procedural_and_skills_status_counts(temp_db, tmp_path, monkeypatch):
    _execute(
        temp_db,
        """
        INSERT INTO pending_fact_candidates (id, session_id, fact, category, confidence, explicit, source, status)
        VALUES ('factcand-1', 'sess', 'User likes compact UI', 'preference', 0.8, 0, 'test', 'PENDING')
        """,
    )
    _execute(
        temp_db,
        """
        INSERT INTO skill_candidates (id, title, description, trigger_description, workflow_json, preferred_tools_json, tags_json, confidence, occurrences, source_episode_ids_json, status)
        VALUES ('skillcand-1', 'Deploy Staging', 'Private detailed workflow', 'deploy staging', '[]', '["shell"]', '["deploy"]', 0.9, 3, '[]', 'READY_FOR_PROMOTION')
        """,
    )
    _execute(
        temp_db,
        """
        INSERT INTO skill_versions (id, skill_id, version, name, description, file_path, content_hash, frontmatter_json, workflow_json, preferred_tools_json, tags_json, enabled, active, author)
        VALUES ('skillver-1', 'deploy-staging', 1, 'Deploy Staging', 'Deploys staging', '.agent/skills/generated/deploy-staging/v0001/SKILL.md', 'hash', '{}', '{}', '[]', '[]', 1, 1, 'generated')
        """,
    )
    _execute(
        temp_db,
        "INSERT INTO skill_usage_stats (skill_id, active_version_id, times_loaded, times_used) VALUES ('deploy-staging', 'skillver-1', 2, 5)",
    )

    semantic = client.get("/api/memory/observability/semantic").json()
    procedural = client.get("/api/memory/observability/procedural").json()
    skills = client.get("/api/memory/observability/skills").json()

    assert semantic["summary"]["pending_candidates"] == 1
    assert procedural["summary"]["ready_for_promotion"] == 1
    assert skills["summary"]["active_versions"] == 1
    assert skills["summary"]["total_times_loaded"] == 2
    assert skills["summary"]["total_times_used"] == 5


def test_skills_endpoint_does_not_reload_or_record_usage(temp_db, monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("observability must not mutate skill runtime usage")

    monkeypatch.setattr("src.memory.skill_reloader.SkillRuntimeReloader.reload_active_skills", fail)
    monkeypatch.setattr("src.memory.skill_reloader.SkillRuntimeReloader.record_skill_used", fail)
    monkeypatch.setattr("src.memory.skill_store.SkillVersionStore.record_used", fail)

    resp = client.get("/api/memory/observability/skills")

    assert resp.status_code == 200
