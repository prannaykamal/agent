import json
import sqlite3
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from src.api.server import app
from src.db import init_db
from src.memory.job_handlers import JobHandlerResult, NoOpMemoryJobHandler
from src.memory.job_router import MemoryJobRouter
from src.memory.job_repository import MemoryJobRepository
from src.memory.jobs import MemoryJobSpec, make_memory_job_id
from src.memory.worker import process_one_memory_job


NOW = datetime(2026, 1, 1, 12, 0, 0)
client = TestClient(app)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "phase3b_worker.db"
    mem_file = tmp_path / "MEMORY.md"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    monkeypatch.setattr("src.config.MEMORY_PATH", mem_file)
    init_db(db_file)
    return db_file


def _ts(value):
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _spec(name, max_attempts=3):
    key = f"phase3b-worker:{name}"
    return MemoryJobSpec(
        job_type="noop_test",
        payload={"schema_version": 1, "name": name},
        idempotency_key=key,
        job_id=make_memory_job_id("noop_test", key),
        session_id="phase3b-worker",
        available_at=_ts(NOW),
    )


NOOP_ROUTER = MemoryJobRouter(handlers={"noop_test": NoOpMemoryJobHandler(job_type="noop_test")})


def _job(db_path, job_id):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM memory_jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row)
    finally:
        conn.close()


def _count(db_path, table_name):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
    finally:
        conn.close()


def _insert_raw_job(db_path, job_id, job_type, payload_json, max_attempts=2):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO memory_jobs (
                id, job_type, status, priority, session_id, idempotency_key,
                payload_json, attempt_count, max_attempts, available_at
            ) VALUES (?, ?, 'QUEUED', 100, 'phase3b-worker', ?, ?, 0, ?, ?)
            """,
            (job_id, job_type, f"idem:{job_id}", payload_json, max_attempts, _ts(NOW)),
        )
        conn.commit()
    finally:
        conn.close()


class FailingRouter:
    def dispatch(self, job):
        return JobHandlerResult(
            success=False,
            result={"handler": "test", "message": "forced failure", "processed": False},
        )


def test_process_one_memory_job_returns_idle_when_queue_empty(temp_db):
    result = process_one_memory_job(worker_id="worker-1", db_path=temp_db, now=NOW)

    assert result.status == "IDLE"
    assert result.processed is False
    assert result.job_id is None


def test_process_one_memory_job_succeeds_with_noop_handler(temp_db):
    repo = MemoryJobRepository(db_path=temp_db)
    enqueued = repo.enqueue(_spec("success"))

    result = process_one_memory_job(worker_id="worker-1", router=NOOP_ROUTER, db_path=temp_db, now=NOW)
    row = _job(temp_db, enqueued.job_id)

    assert result.status == "SUCCEEDED"
    assert result.processed is True
    assert row["status"] == "SUCCEEDED"
    assert json.loads(row["result_json"])["processed"] is False
    assert row["locked_by"] is None
    assert _count(temp_db, "dead_letter_jobs") == 0


def test_handler_failure_retries(temp_db):
    repo = MemoryJobRepository(db_path=temp_db)
    enqueued = repo.enqueue(_spec("retry"))

    result = process_one_memory_job(
        worker_id="worker-1",
        router=FailingRouter(),
        db_path=temp_db,
        now=NOW,
        retry_backoff_seconds=30,
    )
    row = _job(temp_db, enqueued.job_id)

    assert result.status == "RETRYING"
    assert row["status"] == "RETRYING"
    assert row["attempt_count"] == 1
    assert row["available_at"] == "2026-01-01 12:00:30"


def test_handler_failure_at_max_attempts_dead_letters(temp_db):
    repo = MemoryJobRepository(db_path=temp_db)
    enqueued = repo.enqueue(_spec("dead"), max_attempts=1)

    result = process_one_memory_job(
        worker_id="worker-1",
        router=FailingRouter(),
        db_path=temp_db,
        now=NOW,
    )
    row = _job(temp_db, enqueued.job_id)

    assert result.status == "DEAD_LETTERED"
    assert row["status"] == "DEAD_LETTERED"
    assert _count(temp_db, "dead_letter_jobs") == 1


def test_unknown_job_type_retries_then_dead_letters(temp_db):
    _insert_raw_job(temp_db, "unknown-job", "unknown_job", json.dumps({"schema_version": 1}), max_attempts=1)

    result = process_one_memory_job(worker_id="worker-1", db_path=temp_db, now=NOW)
    row = _job(temp_db, "unknown-job")

    assert result.status == "DEAD_LETTERED"
    assert row["status"] == "DEAD_LETTERED"
    assert _count(temp_db, "dead_letter_jobs") == 1


def test_invalid_payload_retries_then_dead_letters(temp_db):
    _insert_raw_job(temp_db, "invalid-job", "cognee_ingest", "{not json", max_attempts=1)

    result = process_one_memory_job(worker_id="worker-1", db_path=temp_db, now=NOW)
    row = _job(temp_db, "invalid-job")

    assert result.status == "DEAD_LETTERED"
    assert row["status"] == "DEAD_LETTERED"
    assert _count(temp_db, "dead_letter_jobs") == 1


def test_worker_step_updates_heartbeat_to_idle_after_success(temp_db):
    repo = MemoryJobRepository(db_path=temp_db)
    repo.enqueue(_spec("heartbeat"))

    process_one_memory_job(worker_id="worker-1", db_path=temp_db, now=NOW)

    conn = sqlite3.connect(temp_db)
    conn.row_factory = sqlite3.Row
    try:
        heartbeat = dict(conn.execute("SELECT * FROM worker_heartbeats WHERE worker_id = 'worker-1'").fetchone())
    finally:
        conn.close()

    assert heartbeat["status"] == "IDLE"
    assert heartbeat["current_job_id"] is None


def test_noop_worker_does_not_write_memory_behavior_tables(temp_db):
    repo = MemoryJobRepository(db_path=temp_db)
    repo.enqueue(_spec("no-memory-writes"))
    untouched = [
        "facts",
        "episodes",
        "summary_blocks",
    ]
    before = {table: _count(temp_db, table) for table in untouched}

    process_one_memory_job(worker_id="worker-1", router=NOOP_ROUTER, db_path=temp_db, now=NOW)

    assert {table: _count(temp_db, table) for table in untouched} == before


def test_chat_still_works_when_worker_is_not_running(temp_db, fake_cognee, fake_jev):
    fake_jev.memory = {"should_store": True, "should_retrieve": False}
    response = client.post(
        "/api/chat",
        json={
            "message": "Hello, do not run the worker automatically.",
            "session_id": "phase3b-chat",
            "provider": "openai",
            "model_name": "gpt-4o-mini",
        },
    )

    assert response.status_code == 200
    assert "response" in response.json()
    # The session write is queued for the worker, not executed inline.
    assert _count(temp_db, "memory_jobs") >= 1
    assert fake_cognee.remember_calls == []
    assert _count(temp_db, "worker_heartbeats") == 0
