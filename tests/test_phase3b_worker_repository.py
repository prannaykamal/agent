import json
import sqlite3
from datetime import datetime, timedelta

import pytest

from src.db import init_db
from src.memory.job_repository import MemoryJobRepository
from src.memory.jobs import MemoryJobSpec, make_memory_job_id


NOW = datetime(2026, 1, 1, 12, 0, 0)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "phase3b_repo.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file


def _ts(value):
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _spec(job_id, priority=100, status_payload=True, available_at=None, max_attempts=3):
    payload = {"schema_version": 1, "job": job_id} if status_payload else {}
    idempotency_key = f"phase3b:{job_id}"
    return MemoryJobSpec(
        job_type="semantic_candidate_extraction",
        payload=payload,
        idempotency_key=idempotency_key,
        job_id=make_memory_job_id("semantic_candidate_extraction", idempotency_key),
        session_id="phase3b-session",
        priority=priority,
        available_at=_ts(available_at or NOW),
    )


def _insert_status_job(db_path, status, job_id):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO memory_jobs (
                id, job_type, status, priority, session_id, idempotency_key,
                payload_json, attempt_count, max_attempts, available_at, locked_by, locked_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                "semantic_candidate_extraction",
                status,
                100,
                "phase3b-session",
                f"idempotency:{job_id}",
                json.dumps({"schema_version": 1}),
                0,
                3,
                _ts(NOW),
                "other-worker" if status == "RUNNING" else None,
                _ts(NOW) if status == "RUNNING" else None,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _job(db_path, job_id):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM memory_jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row)
    finally:
        conn.close()


def test_claim_highest_priority_due_job(temp_db):
    repo = MemoryJobRepository(db_path=temp_db)
    low = repo.enqueue(_spec("low", priority=100))
    high = repo.enqueue(_spec("high", priority=1))

    claimed = repo.claim_next_due_job(worker_id="worker-1", now=NOW)

    assert claimed["id"] == high.job_id
    assert claimed["status"] == "RUNNING"
    assert claimed["locked_by"] == "worker-1"
    assert _job(temp_db, low.job_id)["status"] == "QUEUED"


def test_claim_due_retrying_job(temp_db):
    repo = MemoryJobRepository(db_path=temp_db)
    result = repo.enqueue(_spec("retrying"))
    conn = sqlite3.connect(temp_db)
    try:
        conn.execute(
            "UPDATE memory_jobs SET status = 'RETRYING', available_at = ? WHERE id = ?",
            (_ts(NOW - timedelta(seconds=1)), result.job_id),
        )
        conn.commit()
    finally:
        conn.close()

    claimed = repo.claim_next_due_job(worker_id="worker-1", now=NOW)

    assert claimed["id"] == result.job_id
    assert claimed["status"] == "RUNNING"


def test_does_not_claim_future_or_terminal_or_locked_jobs(temp_db):
    repo = MemoryJobRepository(db_path=temp_db)
    future = repo.enqueue(_spec("future", available_at=NOW + timedelta(hours=1)))
    for status in ("RUNNING", "SUCCEEDED", "FAILED", "DEAD_LETTERED", "CANCELLED"):
        _insert_status_job(temp_db, status, f"job-{status}")

    claimed = repo.claim_next_due_job(worker_id="worker-1", now=NOW)

    assert claimed is None
    assert _job(temp_db, future.job_id)["status"] == "QUEUED"


def test_success_transition_clears_locks_and_writes_result_json(temp_db):
    repo = MemoryJobRepository(db_path=temp_db)
    result = repo.enqueue(_spec("success"))
    claimed = repo.claim_next_due_job(worker_id="worker-1", now=NOW)

    repo.mark_job_succeeded(
        job_id=claimed["id"],
        worker_id="worker-1",
        result={"processed": False, "handler": "noop"},
        now=NOW,
    )

    row = _job(temp_db, result.job_id)
    assert row["status"] == "SUCCEEDED"
    assert json.loads(row["result_json"]) == {"handler": "noop", "processed": False}
    assert row["locked_by"] is None
    assert row["locked_at"] is None
    assert row["completed_at"] == _ts(NOW)


def test_failure_retries_with_deterministic_backoff(temp_db):
    repo = MemoryJobRepository(db_path=temp_db)
    result = repo.enqueue(_spec("retry"))
    claimed = repo.claim_next_due_job(worker_id="worker-1", now=NOW)

    transition = repo.handle_job_failure(
        job=claimed,
        worker_id="worker-1",
        error="boom",
        now=NOW,
        retry_backoff_seconds=30,
    )

    row = _job(temp_db, result.job_id)
    assert transition.status == "RETRYING"
    assert transition.attempt_count == 1
    assert transition.retry_at == _ts(NOW + timedelta(seconds=30))
    assert row["status"] == "RETRYING"
    assert row["attempt_count"] == 1
    assert row["available_at"] == _ts(NOW + timedelta(seconds=30))
    assert row["locked_by"] is None


def test_exhausted_failure_creates_dead_letter_row(temp_db):
    repo = MemoryJobRepository(db_path=temp_db)
    result = repo.enqueue(_spec("dead", max_attempts=1), max_attempts=1)
    claimed = repo.claim_next_due_job(worker_id="worker-1", now=NOW)

    transition = repo.handle_job_failure(
        job=claimed,
        worker_id="worker-1",
        error=RuntimeError("done"),
        error_details={"handler": "test", "error_type": "RuntimeError"},
        now=NOW,
    )

    row = _job(temp_db, result.job_id)
    conn = sqlite3.connect(temp_db)
    conn.row_factory = sqlite3.Row
    try:
        dead = dict(conn.execute("SELECT * FROM dead_letter_jobs WHERE job_id = ?", (result.job_id,)).fetchone())
    finally:
        conn.close()

    assert transition.status == "DEAD_LETTERED"
    assert row["status"] == "DEAD_LETTERED"
    assert row["attempt_count"] == 1
    assert dead["last_error"] == "done"
    assert dead["attempt_count"] == 1
    assert json.loads(dead["error_details_json"])["handler"] == "test"


def test_stale_running_recovery_retries_timed_out_job(temp_db):
    repo = MemoryJobRepository(db_path=temp_db)
    result = repo.enqueue(_spec("stale", available_at=NOW - timedelta(minutes=11)))
    claimed = repo.claim_next_due_job(worker_id="stale-worker", now=NOW - timedelta(minutes=10))

    transitions = repo.recover_stale_running_jobs(
        worker_id="recoverer",
        timeout_seconds=60,
        now=NOW,
    )

    row = _job(temp_db, claimed["id"])
    assert len(transitions) == 1
    assert transitions[0].job_id == result.job_id
    assert row["status"] == "RETRYING"
    assert row["attempt_count"] == 1
