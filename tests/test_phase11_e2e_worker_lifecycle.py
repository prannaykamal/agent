import json
import sqlite3
from datetime import datetime, timedelta

import pytest

from src.db import init_db
from src.memory.job_handlers import JobHandlerResult
from src.memory.job_repository import MemoryJobRepository
from src.memory.jobs import MemoryJobSpec, make_memory_job_id
from src.memory.worker import process_one_memory_job, recover_stale_running_jobs

NOW = datetime(2026, 1, 1, 12, 0, 0)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "phase11_worker.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file


def _ts(value):
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _count(db_path, table):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def _job(db_path, job_id):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return dict(conn.execute("SELECT * FROM memory_jobs WHERE id = ?", (job_id,)).fetchone())
    finally:
        conn.close()


def _spec(name, *, priority=100, available_at=None, max_attempts=3):
    key = f"phase11:{name}"
    return MemoryJobSpec(
        job_type="semantic_candidate_extraction",
        payload={"schema_version": 1, "source": "test", "session_id": "phase11", "turn": {"user_text": "remember that I test workers", "assistant_text": "noted"}, "models": {"secondary_provider": "openai", "secondary_model_name": "gpt-4o-mini"}},
        idempotency_key=key,
        job_id=make_memory_job_id("semantic_candidate_extraction", key),
        session_id="phase11",
        priority=priority,
        available_at=_ts(available_at or NOW),
    )


class FailingRouter:
    def dispatch(self, job):
        return JobHandlerResult(False, {"handler": "phase11", "message": "forced failure", "processed": False}, retryable=True)


class SuccessRouter:
    def dispatch(self, job):
        return JobHandlerResult(True, {"handler": "phase11", "processed": False})


def test_worker_does_not_auto_start_from_startup_api_or_chat_static_scan():
    watched = ["src/startup.py", "src/api/server.py", "src/harness/graph.py"]
    text = "\n".join(open(path, encoding="utf-8").read() for path in watched)
    assert "run_memory_worker_loop(" not in text
    assert "process_one_memory_job(" not in text


def test_process_one_memory_job_success_and_explicit_heartbeat(temp_db):
    repo = MemoryJobRepository(db_path=temp_db)
    enqueued = repo.enqueue(_spec("success"))

    result = process_one_memory_job(worker_id="worker-1", router=SuccessRouter(), db_path=temp_db, now=NOW)

    assert result.status == "SUCCEEDED"
    assert _job(temp_db, enqueued.job_id)["status"] == "SUCCEEDED"
    assert _count(temp_db, "worker_heartbeats") == 1


def test_retryable_failure_and_dead_letter_after_max_attempts(temp_db):
    repo = MemoryJobRepository(db_path=temp_db)
    retry_job = repo.enqueue(_spec("retry"), max_attempts=3)
    dead_job = repo.enqueue(_spec("dead"), max_attempts=1)

    retry_result = process_one_memory_job(worker_id="worker-1", router=FailingRouter(), db_path=temp_db, now=NOW, retry_backoff_seconds=10)
    dead_result = process_one_memory_job(worker_id="worker-1", router=FailingRouter(), db_path=temp_db, now=NOW, retry_backoff_seconds=10)

    assert retry_result.status == "RETRYING"
    assert _job(temp_db, retry_job.job_id)["available_at"] == "2026-01-01 12:00:10"
    assert dead_result.status == "DEAD_LETTERED"
    assert _job(temp_db, dead_job.job_id)["status"] == "DEAD_LETTERED"
    assert _count(temp_db, "dead_letter_jobs") == 1


def test_stale_running_job_recovery(temp_db):
    repo = MemoryJobRepository(db_path=temp_db)
    enqueued = repo.enqueue(_spec("stale", available_at=NOW - timedelta(minutes=10)))
    claimed = repo.claim_next_due_job(worker_id="crashed-worker", now=NOW - timedelta(minutes=10))
    assert claimed["id"] == enqueued.job_id

    results = recover_stale_running_jobs(worker_id="recovery", db_path=temp_db, timeout_seconds=60, now=NOW)

    assert len(results) == 1
    assert results[0].status == "RETRYING"
    assert _job(temp_db, enqueued.job_id)["locked_by"] is None


def test_mixed_queue_priority_and_due_ordering(temp_db):
    repo = MemoryJobRepository(db_path=temp_db)
    future = repo.enqueue(_spec("future", priority=1, available_at=NOW + timedelta(hours=1)))
    low = repo.enqueue(_spec("low", priority=50))
    high = repo.enqueue(_spec("high", priority=5))

    claimed = repo.claim_next_due_job(worker_id="worker-1", now=NOW)

    assert claimed["id"] == high.job_id
    assert _job(temp_db, future.job_id)["status"] == "QUEUED"
    assert _job(temp_db, low.job_id)["status"] == "QUEUED"


def test_unknown_and_invalid_jobs_fail_safely(temp_db):
    conn = sqlite3.connect(temp_db)
    try:
        conn.execute(
            """
            INSERT INTO memory_jobs (id, job_type, status, priority, session_id, idempotency_key, payload_json, attempt_count, max_attempts, available_at)
            VALUES ('unknown-job', 'unknown_job', 'QUEUED', 1, 'phase11', 'idem-unknown', '{}', 0, 1, ?)
            """,
            (_ts(NOW),),
        )
        conn.execute(
            """
            INSERT INTO memory_jobs (id, job_type, status, priority, session_id, idempotency_key, payload_json, attempt_count, max_attempts, available_at)
            VALUES ('invalid-job', 'semantic_candidate_extraction', 'QUEUED', 2, 'phase11', 'idem-invalid', '{bad json', 0, 1, ?)
            """,
            (_ts(NOW),),
        )
        conn.commit()
    finally:
        conn.close()

    first = process_one_memory_job(worker_id="worker-1", db_path=temp_db, now=NOW)
    second = process_one_memory_job(worker_id="worker-1", db_path=temp_db, now=NOW)

    assert first.status == "DEAD_LETTERED"
    assert second.status == "DEAD_LETTERED"
    assert _count(temp_db, "dead_letter_jobs") == 2

