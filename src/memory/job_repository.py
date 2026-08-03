import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.db import get_connection
from src.memory.config import load_memory_config
from src.memory.jobs import (
    EnqueueResult,
    MEMORY_JOB_STATUS_DEAD_LETTERED,
    MEMORY_JOB_STATUS_QUEUED,
    MEMORY_JOB_STATUS_RETRYING,
    MEMORY_JOB_STATUS_RUNNING,
    MEMORY_JOB_STATUS_SUCCEEDED,
    MemoryJobSpec,
    canonical_json,
    sha256_hex,
)


@dataclass(frozen=True)
class FailureTransitionResult:
    job_id: str
    status: str
    attempt_count: int
    retry_at: Optional[str] = None
    dead_letter_id: Optional[str] = None


def _now() -> datetime:
    return datetime.utcnow().replace(microsecond=0)


def _coerce_datetime(value: Optional[datetime]) -> datetime:
    return (value or _now()).replace(microsecond=0)


def _format_ts(value: Optional[datetime] = None) -> str:
    return _coerce_datetime(value).strftime("%Y-%m-%d %H:%M:%S")


def _row_to_dict(row: Any) -> Optional[Dict[str, Any]]:
    return dict(row) if row else None


def _error_text(error: BaseException | str) -> str:
    return str(error)[:1000]


class MemoryJobRepository:
    """Repository for memory queue persistence and worker lifecycle transitions."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path

    def enqueue(self, spec: MemoryJobSpec, max_attempts: int = 3) -> EnqueueResult:
        payload_json = canonical_json(spec.payload)
        json.loads(payload_json)

        conn = get_connection(self.db_path)
        try:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """
                    INSERT INTO memory_jobs (
                        id,
                        job_type,
                        status,
                        priority,
                        session_id,
                        idempotency_key,
                        payload_json,
                        attempt_count,
                        max_attempts,
                        available_at,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, COALESCE(?, datetime('now')), datetime('now'), datetime('now'))
                    """,
                    (
                        spec.job_id,
                        spec.job_type,
                        MEMORY_JOB_STATUS_QUEUED,
                        spec.priority,
                        spec.session_id,
                        spec.idempotency_key,
                        payload_json,
                        max_attempts,
                        spec.available_at,
                    ),
                )
                conn.commit()
                return EnqueueResult(
                    job_id=spec.job_id,
                    idempotency_key=spec.idempotency_key,
                    inserted=True,
                    status=MEMORY_JOB_STATUS_QUEUED,
                )
            except sqlite3.IntegrityError as exc:
                conn.rollback()
                existing = self.get_by_idempotency_key(spec.idempotency_key)
                if existing is not None:
                    return EnqueueResult(
                        job_id=str(existing["id"]),
                        idempotency_key=spec.idempotency_key,
                        inserted=False,
                        status=str(existing["status"]),
                    )
                raise exc
        finally:
            conn.close()

    def get_by_idempotency_key(self, idempotency_key: str) -> Optional[Dict[str, Any]]:
        conn = get_connection(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM memory_jobs WHERE idempotency_key = ?",
                (idempotency_key,),
            )
            return _row_to_dict(cursor.fetchone())
        finally:
            conn.close()

    def get_by_id(self, job_id: str) -> Optional[Dict[str, Any]]:
        conn = get_connection(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM memory_jobs WHERE id = ?", (job_id,))
            return _row_to_dict(cursor.fetchone())
        finally:
            conn.close()

    def count_by_session(self, session_id: str) -> int:
        conn = get_connection(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM memory_jobs WHERE session_id = ?",
                (session_id,),
            )
            return int(cursor.fetchone()[0])
        finally:
            conn.close()

    def list_jobs_for_session(self, session_id: str) -> List[Dict[str, Any]]:
        conn = get_connection(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT *
                FROM memory_jobs
                WHERE session_id = ?
                ORDER BY rowid ASC
                """,
                (session_id,),
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def claim_next_due_job(self, worker_id: str, now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
        now_str = _format_ts(now)
        conn = get_connection(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT *
                FROM memory_jobs
                WHERE status IN (?, ?)
                  AND available_at <= ?
                  AND locked_by IS NULL
                ORDER BY priority ASC, available_at ASC, created_at ASC
                LIMIT 1
                """,
                (MEMORY_JOB_STATUS_QUEUED, MEMORY_JOB_STATUS_RETRYING, now_str),
            )
            candidate = cursor.fetchone()
            if candidate is None:
                conn.commit()
                return None

            job_id = candidate["id"]
            cursor.execute(
                """
                UPDATE memory_jobs
                SET status = ?,
                    locked_by = ?,
                    locked_at = ?,
                    started_at = COALESCE(started_at, ?),
                    updated_at = ?
                WHERE id = ?
                  AND status IN (?, ?)
                  AND locked_by IS NULL
                """,
                (
                    MEMORY_JOB_STATUS_RUNNING,
                    worker_id,
                    now_str,
                    now_str,
                    now_str,
                    job_id,
                    MEMORY_JOB_STATUS_QUEUED,
                    MEMORY_JOB_STATUS_RETRYING,
                ),
            )
            if cursor.rowcount != 1:
                conn.commit()
                return None

            cursor.execute("SELECT * FROM memory_jobs WHERE id = ?", (job_id,))
            claimed = _row_to_dict(cursor.fetchone())
            conn.commit()
            return claimed
        finally:
            conn.close()

    def mark_job_succeeded(
        self,
        job_id: str,
        worker_id: str,
        result: Dict[str, Any],
        now: Optional[datetime] = None,
    ) -> None:
        now_str = _format_ts(now)
        result_json = canonical_json(result)
        json.loads(result_json)
        conn = get_connection(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE memory_jobs
                SET status = ?,
                    result_json = ?,
                    error_message = NULL,
                    locked_by = NULL,
                    locked_at = NULL,
                    completed_at = ?,
                    updated_at = ?
                WHERE id = ?
                  AND status = ?
                  AND locked_by = ?
                """,
                (
                    MEMORY_JOB_STATUS_SUCCEEDED,
                    result_json,
                    now_str,
                    now_str,
                    job_id,
                    MEMORY_JOB_STATUS_RUNNING,
                    worker_id,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(f"Job '{job_id}' is not running for worker '{worker_id}'")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def handle_job_failure(
        self,
        job: Dict[str, Any],
        worker_id: str,
        error: BaseException | str,
        error_details: Optional[Dict[str, Any]] = None,
        now: Optional[datetime] = None,
        retry_backoff_seconds: Optional[int] = None,
    ) -> FailureTransitionResult:
        current_attempts = int(job.get("attempt_count") or 0)
        max_attempts = int(job.get("max_attempts") or 1)
        next_attempt = current_attempts + 1
        now_dt = _coerce_datetime(now)
        now_str = _format_ts(now_dt)
        err = _error_text(error)

        if next_attempt >= max_attempts:
            return self._move_to_dead_letter_with_attempt(
                job=job,
                worker_id=worker_id,
                error=err,
                attempt_count=next_attempt,
                error_details=error_details,
                now=now_dt,
            )

        if retry_backoff_seconds is None:
            retry_backoff_seconds = load_memory_config().queue.retry_backoff_seconds
        retry_at = _format_ts(now_dt + timedelta(seconds=retry_backoff_seconds * next_attempt))

        conn = get_connection(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE memory_jobs
                SET status = ?,
                    attempt_count = ?,
                    available_at = ?,
                    error_message = ?,
                    locked_by = NULL,
                    locked_at = NULL,
                    updated_at = ?
                WHERE id = ?
                  AND status = ?
                  AND locked_by = ?
                """,
                (
                    MEMORY_JOB_STATUS_RETRYING,
                    next_attempt,
                    retry_at,
                    err,
                    now_str,
                    job["id"],
                    MEMORY_JOB_STATUS_RUNNING,
                    worker_id,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(f"Job '{job['id']}' is not running for worker '{worker_id}'")
            conn.commit()
            return FailureTransitionResult(
                job_id=str(job["id"]),
                status=MEMORY_JOB_STATUS_RETRYING,
                attempt_count=next_attempt,
                retry_at=retry_at,
            )
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def move_to_dead_letter(
        self,
        job: Dict[str, Any],
        worker_id: str,
        error: BaseException | str,
        error_details: Optional[Dict[str, Any]] = None,
        now: Optional[datetime] = None,
    ) -> FailureTransitionResult:
        return self._move_to_dead_letter_with_attempt(
            job=job,
            worker_id=worker_id,
            error=_error_text(error),
            attempt_count=int(job.get("attempt_count") or 0) + 1,
            error_details=error_details,
            now=_coerce_datetime(now),
        )

    def _move_to_dead_letter_with_attempt(
        self,
        job: Dict[str, Any],
        worker_id: str,
        error: str,
        attempt_count: int,
        error_details: Optional[Dict[str, Any]],
        now: datetime,
    ) -> FailureTransitionResult:
        now_str = _format_ts(now)
        base_dead_letter_id = f"dlj_{job['id']}_{attempt_count}"
        dead_letter_id = base_dead_letter_id
        details = dict(error_details or {})
        details.setdefault("worker_id", worker_id)
        details.setdefault("job_status_before_dead_letter", job.get("status"))
        details.setdefault("max_attempts", job.get("max_attempts"))
        details_json = canonical_json(details)

        conn = get_connection(self.db_path)
        try:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """
                    INSERT INTO dead_letter_jobs (
                        id,
                        job_id,
                        job_type,
                        session_id,
                        idempotency_key,
                        payload_json,
                        last_error,
                        error_details_json,
                        attempt_count,
                        failed_at,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        dead_letter_id,
                        job["id"],
                        job["job_type"],
                        job.get("session_id"),
                        job.get("idempotency_key"),
                        job.get("payload_json") or "{}",
                        error,
                        details_json,
                        attempt_count,
                        now_str,
                        now_str,
                    ),
                )
            except sqlite3.IntegrityError:
                dead_letter_id = f"{base_dead_letter_id}_{sha256_hex(now_str)[:8]}"
                cursor.execute(
                    """
                    INSERT INTO dead_letter_jobs (
                        id, job_id, job_type, session_id, idempotency_key, payload_json,
                        last_error, error_details_json, attempt_count, failed_at, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        dead_letter_id,
                        job["id"],
                        job["job_type"],
                        job.get("session_id"),
                        job.get("idempotency_key"),
                        job.get("payload_json") or "{}",
                        error,
                        details_json,
                        attempt_count,
                        now_str,
                        now_str,
                    ),
                )

            cursor.execute(
                """
                UPDATE memory_jobs
                SET status = ?,
                    attempt_count = ?,
                    error_message = ?,
                    locked_by = NULL,
                    locked_at = NULL,
                    completed_at = ?,
                    updated_at = ?
                WHERE id = ?
                  AND status = ?
                  AND locked_by = ?
                """,
                (
                    MEMORY_JOB_STATUS_DEAD_LETTERED,
                    attempt_count,
                    error,
                    now_str,
                    now_str,
                    job["id"],
                    MEMORY_JOB_STATUS_RUNNING,
                    worker_id,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(f"Job '{job['id']}' is not running for worker '{worker_id}'")
            conn.commit()
            return FailureTransitionResult(
                job_id=str(job["id"]),
                status=MEMORY_JOB_STATUS_DEAD_LETTERED,
                attempt_count=attempt_count,
                dead_letter_id=dead_letter_id,
            )
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def recover_stale_running_jobs(
        self,
        worker_id: str,
        timeout_seconds: int,
        now: Optional[datetime] = None,
    ) -> List[FailureTransitionResult]:
        now_dt = _coerce_datetime(now)
        cutoff = _format_ts(now_dt - timedelta(seconds=timeout_seconds))
        conn = get_connection(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT *
                FROM memory_jobs
                WHERE status = ?
                  AND locked_at IS NOT NULL
                  AND locked_at <= ?
                ORDER BY locked_at ASC
                """,
                (MEMORY_JOB_STATUS_RUNNING, cutoff),
            )
            jobs = [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

        results = []
        for job in jobs:
            owner = str(job.get("locked_by") or worker_id)
            results.append(
                self.handle_job_failure(
                    job=job,
                    worker_id=owner,
                    error="Worker lock timed out",
                    error_details={
                        "recovered_by": worker_id,
                        "timeout_seconds": timeout_seconds,
                        "error_type": "WorkerTimeout",
                    },
                    now=now_dt,
                )
            )
        return results

    def upsert_worker_heartbeat(
        self,
        worker_id: str,
        status: str,
        current_job_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        now: Optional[datetime] = None,
    ) -> None:
        now_str = _format_ts(now)
        metadata_json = canonical_json(metadata or {})
        conn = get_connection(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO worker_heartbeats (
                    worker_id,
                    worker_type,
                    status,
                    current_job_id,
                    last_heartbeat_at,
                    started_at,
                    metadata_json,
                    created_at,
                    updated_at
                ) VALUES (?, 'memory', ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(worker_id) DO UPDATE SET
                    status = excluded.status,
                    current_job_id = excluded.current_job_id,
                    last_heartbeat_at = excluded.last_heartbeat_at,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    worker_id,
                    status,
                    current_job_id,
                    now_str,
                    now_str,
                    metadata_json,
                    now_str,
                    now_str,
                ),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
