import os
import socket
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Event
from typing import Any, Dict, Optional

from src.memory.config import load_memory_config
from src.memory.job_repository import FailureTransitionResult, MemoryJobRepository
from src.memory.job_router import MemoryJobRouter


@dataclass(frozen=True)
class MemoryWorkerStepResult:
    worker_id: str
    job_id: Optional[str]
    job_type: Optional[str]
    status: str
    processed: bool
    message: str
    failure_transition: Optional[FailureTransitionResult] = None


def _worker_metadata() -> Dict[str, Any]:
    return {
        "worker_type": "memory",
        "phase": "3B",
        "pid": os.getpid(),
        "hostname": socket.gethostname(),
        "worker_version": 1,
    }


def process_one_memory_job(
    worker_id: str,
    router: Optional[MemoryJobRouter] = None,
    db_path: Optional[Path] = None,
    now: Optional[datetime] = None,
    retry_backoff_seconds: Optional[int] = None,
) -> MemoryWorkerStepResult:
    repository = MemoryJobRepository(db_path=db_path)
    active_router = router or MemoryJobRouter()

    try:
        job = repository.claim_next_due_job(worker_id=worker_id, now=now)
        if job is None:
            repository.upsert_worker_heartbeat(
                worker_id=worker_id,
                status="IDLE",
                current_job_id=None,
                metadata=_worker_metadata(),
                now=now,
            )
            return MemoryWorkerStepResult(
                worker_id=worker_id,
                job_id=None,
                job_type=None,
                status="IDLE",
                processed=False,
                message="No due memory job found",
            )

        repository.upsert_worker_heartbeat(
            worker_id=worker_id,
            status="RUNNING",
            current_job_id=str(job["id"]),
            metadata=_worker_metadata(),
            now=now,
        )

        try:
            handler_result = active_router.dispatch(job)
            if handler_result.success:
                repository.mark_job_succeeded(
                    job_id=str(job["id"]),
                    worker_id=worker_id,
                    result=handler_result.result,
                    now=now,
                )
                repository.upsert_worker_heartbeat(
                    worker_id=worker_id,
                    status="IDLE",
                    current_job_id=None,
                    metadata=_worker_metadata(),
                    now=now,
                )
                return MemoryWorkerStepResult(
                    worker_id=worker_id,
                    job_id=str(job["id"]),
                    job_type=str(job["job_type"]),
                    status="SUCCEEDED",
                    processed=True,
                    message="Memory job processed by safe handler",
                )

            transition = repository.handle_job_failure(
                job=job,
                worker_id=worker_id,
                error=handler_result.result.get("message", "Memory job handler failed"),
                error_details={
                    "handler": handler_result.result.get("handler", "unknown"),
                    "job_type": job.get("job_type"),
                    "retryable": handler_result.retryable,
                    "result": handler_result.result,
                },
                now=now,
                retry_backoff_seconds=retry_backoff_seconds,
            )
            repository.upsert_worker_heartbeat(
                worker_id=worker_id,
                status="IDLE",
                current_job_id=None,
                metadata=_worker_metadata(),
                now=now,
            )
            return MemoryWorkerStepResult(
                worker_id=worker_id,
                job_id=str(job["id"]),
                job_type=str(job["job_type"]),
                status=transition.status,
                processed=True,
                message="Memory job handler failed",
                failure_transition=transition,
            )
        except Exception as exc:
            transition = repository.handle_job_failure(
                job=job,
                worker_id=worker_id,
                error=exc,
                error_details={
                    "handler": "router",
                    "job_type": job.get("job_type"),
                    "error_type": type(exc).__name__,
                },
                now=now,
                retry_backoff_seconds=retry_backoff_seconds,
            )
            repository.upsert_worker_heartbeat(
                worker_id=worker_id,
                status="IDLE",
                current_job_id=None,
                metadata=_worker_metadata(),
                now=now,
            )
            return MemoryWorkerStepResult(
                worker_id=worker_id,
                job_id=str(job["id"]),
                job_type=str(job["job_type"]),
                status=transition.status,
                processed=True,
                message=str(exc),
                failure_transition=transition,
            )
    except Exception as exc:
        try:
            repository.upsert_worker_heartbeat(
                worker_id=worker_id,
                status="ERROR",
                current_job_id=None,
                metadata={**_worker_metadata(), "error_type": type(exc).__name__},
                now=now,
            )
        except Exception:
            pass
        return MemoryWorkerStepResult(
            worker_id=worker_id,
            job_id=None,
            job_type=None,
            status="ERROR",
            processed=False,
            message=str(exc),
        )


def recover_stale_running_jobs(
    worker_id: str,
    db_path: Optional[Path] = None,
    timeout_seconds: Optional[int] = None,
    now: Optional[datetime] = None,
) -> list[FailureTransitionResult]:
    repository = MemoryJobRepository(db_path=db_path)
    if timeout_seconds is None:
        timeout_seconds = load_memory_config().queue.job_timeout_seconds
    return repository.recover_stale_running_jobs(
        worker_id=worker_id,
        timeout_seconds=timeout_seconds,
        now=now,
    )


def run_memory_worker_loop(
    worker_id: str = "memory-worker-1",
    interval_seconds: int = 5,
    stop_event: Optional[Event] = None,
    db_path: Optional[Path] = None,
) -> None:
    if stop_event is None:
        stop_event = Event()

    repository = MemoryJobRepository(db_path=db_path)
    repository.upsert_worker_heartbeat(
        worker_id=worker_id,
        status="STARTING",
        current_job_id=None,
        metadata=_worker_metadata(),
    )
    repository.upsert_worker_heartbeat(
        worker_id=worker_id,
        status="IDLE",
        current_job_id=None,
        metadata=_worker_metadata(),
    )

    try:
        while not stop_event.is_set():
            result = process_one_memory_job(worker_id=worker_id, db_path=db_path)
            if not result.processed:
                stop_event.wait(interval_seconds)
    finally:
        repository.upsert_worker_heartbeat(
            worker_id=worker_id,
            status="STOPPING",
            current_job_id=None,
            metadata=_worker_metadata(),
        )
        repository.upsert_worker_heartbeat(
            worker_id=worker_id,
            status="STOPPED",
            current_job_id=None,
            metadata=_worker_metadata(),
        )
