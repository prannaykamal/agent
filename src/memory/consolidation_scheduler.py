"""Enqueue semantic consolidation from the worker idle path only.

The chat graph must never import or call this module.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Sequence

from src.db import get_connection
from src.memory.config import load_memory_config
from src.memory.jobs import enqueue_semantic_consolidation_job
from src.memory.semantic_consolidation import SemanticConsolidationService


LAST_DAILY_IDLE_AT_KEY = "last_daily_idle_at"
DEFAULT_IDLE_WORKER_ID = "memory-idle-scheduler"


def list_consolidation_session_ids(db_path: Optional[Path] = None) -> List[str]:
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT session_id FROM pending_fact_candidates WHERE status = 'PENDING' AND session_id IS NOT NULL
            UNION
            SELECT session_id FROM structured_episodes WHERE session_id IS NOT NULL
            """
        ).fetchall()
        sessions = []
        seen = set()
        for row in rows:
            session_id = str(row["session_id"] if hasattr(row, "keys") else row[0] or "").strip()
            if session_id and session_id not in seen:
                seen.add(session_id)
                sessions.append(session_id)
        return sessions
    except Exception:
        return []
    finally:
        conn.close()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_last_daily_idle_at(value: object) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _as_utc(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    return _as_utc(parsed)


def _should_run_daily_idle(last_daily_idle_at: Optional[datetime], now: datetime, interval_seconds: int) -> bool:
    if last_daily_idle_at is None:
        return True
    elapsed = (_as_utc(now) - _as_utc(last_daily_idle_at)).total_seconds()
    return elapsed >= max(0, int(interval_seconds))


def _read_last_daily_idle_at(db_path: Optional[Path], worker_id: str) -> Optional[datetime]:
    from src.memory.job_repository import MemoryJobRepository

    metadata = MemoryJobRepository(db_path=db_path).get_worker_heartbeat_metadata(worker_id)
    return _parse_last_daily_idle_at(metadata.get(LAST_DAILY_IDLE_AT_KEY))


def _persist_last_daily_idle_at(db_path: Optional[Path], worker_id: str, now: datetime) -> None:
    from src.memory.job_repository import MemoryJobRepository

    repository = MemoryJobRepository(db_path=db_path)
    existing = repository.get_worker_heartbeat(worker_id) or {}
    metadata = dict(existing.get("metadata") or {})
    metadata[LAST_DAILY_IDLE_AT_KEY] = _as_utc(now).replace(microsecond=0).isoformat()
    repository.upsert_worker_heartbeat(
        worker_id=worker_id,
        status=str(existing.get("status") or "IDLE"),
        current_job_id=existing.get("current_job_id"),
        metadata=metadata,
        now=now,
    )


def maybe_enqueue_idle_semantic_consolidation(
    *,
    db_path: Optional[Path] = None,
    now: Optional[datetime] = None,
    session_ids: Optional[Sequence[str]] = None,
    worker_id: Optional[str] = None,
) -> int:
    """Evaluate existing triggers and enqueue consolidation jobs. Idempotent."""
    sessions = list(session_ids) if session_ids is not None else list_consolidation_session_ids(db_path=db_path)
    if not sessions:
        return 0
    moment = now or datetime.now(timezone.utc)
    config = load_memory_config()
    interval_seconds = int(config.queue.idle_maintenance_interval_seconds)
    active_worker_id = str(worker_id or DEFAULT_IDLE_WORKER_ID)
    last_daily = _read_last_daily_idle_at(db_path, active_worker_id)
    run_daily = _should_run_daily_idle(last_daily, moment, interval_seconds)
    maintenance_date = moment.date().isoformat() if run_daily else None
    service = SemanticConsolidationService(db_path=db_path)
    enqueued = 0
    for session_id in sessions:
        try:
            triggers = service.evaluate_triggers(str(session_id), maintenance_date=maintenance_date)
        except Exception:
            continue
        for trigger in triggers:
            if not trigger.should_enqueue:
                continue
            try:
                result = enqueue_semantic_consolidation_job(
                    session_id=trigger.session_id,
                    trigger_type=trigger.trigger_type,
                    window_key=trigger.window_key,
                    primary_provider=config.primary_llm.provider,
                    primary_model_name=config.primary_llm.model_name,
                    secondary_provider=config.secondary_llm.provider,
                    secondary_model_name=config.secondary_llm.model_name,
                    maintenance_date=trigger.maintenance_date,
                    queue=None if db_path is None else _queue_for(db_path),
                )
            except Exception:
                continue
            if result is not None:
                enqueued += 1
    if run_daily:
        try:
            _persist_last_daily_idle_at(db_path, active_worker_id, moment)
        except Exception:
            pass
    return enqueued


def _queue_for(db_path: Path):
    from src.memory.job_repository import MemoryJobRepository
    from src.memory.jobs import SQLiteMemoryJobQueue

    return SQLiteMemoryJobQueue(repository=MemoryJobRepository(db_path=db_path))
