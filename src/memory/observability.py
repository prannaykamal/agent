from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from src.db import get_connection
from src.memory.retrieval_gate import should_retrieve_memory

SENSITIVE_KEY_PATTERNS = (
    "api_key",
    "apikey",
    "token",
    "secret",
    "password",
    "credential",
    "authorization",
)

HIDDEN_REASONING_KEY_PATTERNS = (
    "chain_of_thought",
    "scratchpad",
    "hidden_reasoning",
    "reasoning_trace",
)

CONTENT_KEY_PATTERNS = (
    "prompt",
    "raw_turn",
    "raw_turns",
    "messages",
    "message",
    "message_text",
    "conversation",
    "rationale",
    "llm_output",
    "candidate_text",
    "payload",
    "fact",
    "summary",
    "content",
)

STRUCTURAL_KEY_ALLOWLIST = {
    "id",
    "job_id",
    "worker_id",
    "candidate_id",
    "skill_id",
    "skill_version_id",
    "approval_request_id",
    "source_job_id",
    "source_episode_id",
    "source_message_id",
    "session_id",
    "status",
    "job_type",
    "schema_version",
    "version",
    "created_at",
    "updated_at",
    "failed_at",
    "started_at",
    "completed_at",
    "available_at",
    "locked_at",
    "last_heartbeat_at",
    "attempt_count",
    "max_attempts",
    "priority",
    "count",
    "total",
    "action",
    "category",
    "confidence",
    "explicit",
    "source",
}

REQUIRED_MEMORY_TABLES = (
    "memory_jobs",
    "dead_letter_jobs",
    "worker_heartbeats",
    "summary_blocks",
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso_now() -> str:
    return _utc_now().isoformat().replace("+00:00", "Z")


def _parse_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
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
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _age_seconds(value: Any) -> Optional[int]:
    parsed = _parse_datetime(value)
    if parsed is None:
        return None
    return max(0, int((_utc_now() - parsed).total_seconds()))


def truncate_preview(text: Any, limit: int = 240) -> str:
    normalized = " ".join(str(text or "").split())
    capped = max(0, int(limit))
    if len(normalized) <= capped:
        return normalized
    if capped <= 3:
        return normalized[:capped]
    return normalized[: capped - 3].rstrip() + "..."


def safe_json_loads(value: Any, default: Any = None) -> Any:
    if value is None or value == "":
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except Exception:
        return default


def _matches_key(key: str, patterns: Iterable[str]) -> bool:
    lowered = str(key or "").lower()
    return any(pattern in lowered for pattern in patterns)


def redact_observability_value(key: str, value: Any, *, include_preview: bool = True) -> Any:
    lowered = str(key or "").lower()
    if lowered in STRUCTURAL_KEY_ALLOWLIST:
        return value
    if _matches_key(lowered, SENSITIVE_KEY_PATTERNS) or _matches_key(lowered, HIDDEN_REASONING_KEY_PATTERNS):
        return "[REDACTED]"
    if _matches_key(lowered, CONTENT_KEY_PATTERNS):
        if include_preview:
            return {"preview": truncate_preview(value), "redacted": True}
        return "[REDACTED]"
    if isinstance(value, dict):
        return redact_observability_payload(value, include_preview=include_preview)
    if isinstance(value, list):
        return [redact_observability_payload(item, include_preview=include_preview) for item in value]
    return value


def redact_observability_payload(payload: Any, *, include_preview: bool = True) -> Any:
    if isinstance(payload, dict):
        return {
            str(key): redact_observability_value(str(key), value, include_preview=include_preview)
            for key, value in payload.items()
        }
    if isinstance(payload, list):
        return [redact_observability_payload(item, include_preview=include_preview) for item in payload]
    if isinstance(payload, str):
        return {"preview": truncate_preview(payload), "redacted": True} if include_preview else "[REDACTED]"
    return payload


def _rows(sql: str, params: Sequence[Any] = (), db_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    conn = get_connection(db_path)
    try:
        return [dict(row) for row in conn.execute(sql, tuple(params)).fetchall()]
    finally:
        conn.close()


def _one(sql: str, params: Sequence[Any] = (), db_path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    conn = get_connection(db_path)
    try:
        row = conn.execute(sql, tuple(params)).fetchone()
        return dict(row) if row is not None else None
    finally:
        conn.close()


def _table_names(db_path: Optional[Path] = None) -> set[str]:
    rows = _rows("SELECT name FROM sqlite_master WHERE type IN ('table', 'virtual table')", db_path=db_path)
    return {str(row["name"]) for row in rows}


def _count(table: str, db_path: Optional[Path] = None) -> int:
    row = _one(f"SELECT COUNT(*) AS count FROM {table}", db_path=db_path)
    return int(row["count"] if row else 0)


def _count_by(table: str, column: str, db_path: Optional[Path] = None) -> Dict[str, int]:
    rows = _rows(f"SELECT {column} AS key, COUNT(*) AS count FROM {table} GROUP BY {column}", db_path=db_path)
    return {str(row["key"]): int(row["count"] or 0) for row in rows}


def _latest(table: str, column: str = "created_at", db_path: Optional[Path] = None) -> Optional[str]:
    row = _one(f"SELECT MAX({column}) AS latest FROM {table}", db_path=db_path)
    return row.get("latest") if row else None


def get_memory_health_summary(db_path: Optional[Path] = None, *, stale_after_seconds: int = 120) -> Dict[str, Any]:
    try:
        tables = _table_names(db_path)
        missing = [table for table in REQUIRED_MEMORY_TABLES if table not in tables]
        migration = _one("SELECT MAX(version) AS version FROM schema_migrations", db_path=db_path)
        queue_status = _count_by("memory_jobs", "status", db_path) if "memory_jobs" in tables else {}
        dead_letter_count = _count("dead_letter_jobs", db_path) if "dead_letter_jobs" in tables else 0
        worker_summary = get_worker_observability(db_path=db_path, stale_after_seconds=stale_after_seconds)["summary"] if "worker_heartbeats" in tables else {"total": 0, "active": 0, "stale": 0, "last_heartbeat_at": None}
        long_term = get_long_term_memory_observability(db_path=db_path)
        status = "OK"
        if missing:
            status = "ERROR"
        elif dead_letter_count or worker_summary.get("stale", 0) or queue_status.get("FAILED", 0) or not long_term.get("available"):
            status = "DEGRADED"
        return {
            "status": status,
            "generated_at": _iso_now(),
            "schema": {
                "required_tables_present": not missing,
                "missing_tables": missing,
                "migration_version": migration.get("version") if migration else None,
            },
            "queue": {
                "total_jobs": sum(queue_status.values()),
                "by_status": queue_status,
                "oldest_queued_at": (_one("SELECT MIN(created_at) AS value FROM memory_jobs WHERE status = 'QUEUED'", db_path=db_path) or {}).get("value"),
                "dead_letter_count": dead_letter_count,
            },
            "workers": {
                "total_workers": worker_summary.get("total", 0),
                "active_workers": worker_summary.get("active", 0),
                "stale_workers": worker_summary.get("stale", 0),
                "last_heartbeat_at": worker_summary.get("last_heartbeat_at"),
            },
            "long_term": long_term,
        }
    except Exception as exc:
        return {"status": "ERROR", "generated_at": _iso_now(), "error": f"{type(exc).__name__}: {exc}"}


def get_jobs_observability(
    *,
    db_path: Optional[Path] = None,
    session_id: Optional[str] = None,
    status: Optional[str] = None,
    job_type: Optional[str] = None,
    limit: int = 50,
    include_payload: bool = False,
) -> Dict[str, Any]:
    capped_limit = min(max(1, int(limit)), 200)
    clauses: List[str] = []
    params: List[Any] = []
    if session_id:
        clauses.append("session_id = ?")
        params.append(session_id)
    if status:
        clauses.append("status = ?")
        params.append(status)
    if job_type:
        clauses.append("job_type = ?")
        params.append(job_type)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    summary_rows = _rows(f"SELECT status, job_type, created_at FROM memory_jobs{where}", params, db_path)
    jobs = _rows(
        f"SELECT * FROM memory_jobs{where} ORDER BY created_at DESC, id DESC LIMIT ?",
        [*params, capped_limit],
        db_path,
    )
    by_status: Dict[str, int] = {}
    by_type: Dict[str, int] = {}
    created_values = []
    for row in summary_rows:
        by_status[str(row.get("status"))] = by_status.get(str(row.get("status")), 0) + 1
        by_type[str(row.get("job_type"))] = by_type.get(str(row.get("job_type")), 0) + 1
        if row.get("created_at"):
            created_values.append(str(row["created_at"]))
    rendered = []
    for row in jobs:
        payload = None
        if include_payload:
            payload = redact_observability_payload(safe_json_loads(row.get("payload_json"), {}))
        rendered.append(
            {
                "id": row.get("id"),
                "job_type": row.get("job_type"),
                "status": row.get("status"),
                "priority": row.get("priority"),
                "session_id": row.get("session_id"),
                "attempt_count": row.get("attempt_count"),
                "max_attempts": row.get("max_attempts"),
                "available_at": row.get("available_at"),
                "locked_by": row.get("locked_by"),
                "locked_at": row.get("locked_at"),
                "last_error": truncate_preview(row.get("error_message") or "", 240) or None,
                "created_at": row.get("created_at"),
                "updated_at": row.get("updated_at"),
                "payload": payload,
                "payload_redacted": True,
            }
        )
    return {
        "summary": {
            "total": len(summary_rows),
            "by_status": by_status,
            "by_type": by_type,
            "oldest_queued_at": (_one(f"SELECT MIN(created_at) AS value FROM memory_jobs{where} AND status = 'QUEUED'" if where else "SELECT MIN(created_at) AS value FROM memory_jobs WHERE status = 'QUEUED'", params, db_path) or {}).get("value"),
            "newest_created_at": max(created_values) if created_values else None,
        },
        "jobs": rendered,
    }


_JOB_RESULT_FIELDS = ("processed", "merged", "outcome", "skipped", "deferred", "merged_write_count", "documents_added", "message")


def get_memory_job_status(job_id: str, db_path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """One job's status plus a fixed allowlist of result fields; never payload text."""
    row = _one(
        "SELECT id, job_type, status, session_id, attempt_count, max_attempts, error_message, result_json, created_at, updated_at, completed_at FROM memory_jobs WHERE id = ?",
        (job_id,),
        db_path=db_path,
    )
    if row is None:
        return None
    result = safe_json_loads(row.get("result_json"), {}) or {}
    return {
        "id": row["id"],
        "job_type": row["job_type"],
        "status": row["status"],
        "session_id": row["session_id"],
        "attempt_count": row["attempt_count"],
        "max_attempts": row["max_attempts"],
        "last_error": truncate_preview(row.get("error_message") or "", 240) or None,
        "result": {key: result[key] for key in _JOB_RESULT_FIELDS if isinstance(result, dict) and key in result},
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "completed_at": row["completed_at"],
    }


def get_worker_observability(
    *,
    db_path: Optional[Path] = None,
    stale_after_seconds: int = 120,
    include_host_metadata: bool = False,
) -> Dict[str, Any]:
    stale_after = max(1, int(stale_after_seconds))
    rows = _rows("SELECT * FROM worker_heartbeats ORDER BY last_heartbeat_at DESC", db_path=db_path)
    workers = []
    stale_count = 0
    active_count = 0
    for row in rows:
        age = _age_seconds(row.get("last_heartbeat_at"))
        stale = age is None or age > stale_after
        stale_count += 1 if stale else 0
        active_count += 0 if stale else 1
        metadata = safe_json_loads(row.get("metadata_json"), {}) or {}
        if not include_host_metadata:
            metadata.pop("hostname", None)
            metadata.pop("pid", None)
        workers.append(
            {
                "worker_id": row.get("worker_id"),
                "status": row.get("status"),
                "current_job_id": row.get("current_job_id"),
                "last_heartbeat_at": row.get("last_heartbeat_at"),
                "age_seconds": age,
                "stale": stale,
                "metadata": redact_observability_payload(metadata),
            }
        )
    heartbeat_values = [str(row.get("last_heartbeat_at")) for row in rows if row.get("last_heartbeat_at")]
    return {"summary": {"total": len(rows), "active": active_count, "stale": stale_count, "last_heartbeat_at": max(heartbeat_values) if heartbeat_values else None}, "workers": workers}


def get_dead_letter_observability(
    *,
    db_path: Optional[Path] = None,
    limit: int = 50,
    include_details: bool = False,
) -> Dict[str, Any]:
    capped_limit = min(max(1, int(limit)), 200)
    rows = _rows("SELECT * FROM dead_letter_jobs ORDER BY failed_at DESC, id DESC LIMIT ?", [capped_limit], db_path)
    by_type = _count_by("dead_letter_jobs", "job_type", db_path)
    rendered = []
    for row in rows:
        details = None
        if include_details:
            details = redact_observability_payload(safe_json_loads(row.get("error_details_json"), {}))
        rendered.append(
            {
                "id": row.get("id"),
                "job_id": row.get("job_id"),
                "job_type": row.get("job_type"),
                "session_id": row.get("session_id"),
                "error_message": truncate_preview(row.get("last_error") or "", 240),
                "attempt_count": row.get("attempt_count"),
                "created_at": row.get("created_at"),
                "failed_at": row.get("failed_at"),
                "details": details,
                "details_redacted": True,
            }
        )
    return {"summary": {"total": _count("dead_letter_jobs", db_path), "by_job_type": by_type, "newest_created_at": _latest("dead_letter_jobs", "created_at", db_path)}, "dead_letters": rendered}


def get_long_term_memory_observability(db_path: Optional[Path] = None) -> Dict[str, Any]:
    """Report cognee backend status plus ingest/cognify queue counts. Never triggers cognee work."""
    from src.memory.cognee_memory import get_cognee_memory

    try:
        backend = get_cognee_memory().status()
    except Exception as exc:
        backend = {"backend": "cognee", "available": False, "error": f"{type(exc).__name__}: {exc}"}
    backend["error"] = truncate_preview(backend.get("error"), 240) if backend.get("error") else None
    pipeline: Dict[str, Any] = {}
    if "memory_jobs" in _table_names(db_path):
        for job_type in ("memory_session_write", "memory_session_merge", "cognee_ingest"):
            rows = _rows(
                "SELECT status, COUNT(*) AS count FROM memory_jobs WHERE job_type = ? GROUP BY status",
                (job_type,),
                db_path=db_path,
            )
            last = _one(
                "SELECT MAX(completed_at) AS value FROM memory_jobs WHERE job_type = ? AND status = 'SUCCEEDED'",
                (job_type,),
                db_path=db_path,
            )
            pipeline[job_type] = {
                "by_status": {str(row["status"]): int(row["count"]) for row in rows},
                "last_succeeded_at": (last or {}).get("value"),
            }
    from src.memory.jev import get_jev_client

    jev = get_jev_client()
    # Endpoint URLs can embed credentials, so only report whether Jev is configured and which model.
    jev_status = {
        "configured": jev.available,
        "model": jev.config.model or None,
        "tool_review_enabled": jev.config.tool_review_enabled,
    }
    return {**backend, "jev": jev_status, "pipeline": pipeline}


def get_retrieval_trace(
    *,
    query: str,
    session_id: Optional[str] = None,
    include_candidates: bool = True,
    include_prompt_block: bool = False,
    max_candidates: int = 20,
    search_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Run the same read-only recall the chat path uses and report what it returned."""
    from src.memory.cognee_memory import get_cognee_memory

    clean_query = " ".join(str(query or "").split())
    if not clean_query:
        raise ValueError("query must be non-empty")
    gate_allowed = should_retrieve_memory(clean_query)
    memory = get_cognee_memory()
    response: Dict[str, Any] = {
        "query": clean_query,
        "session_id": session_id,
        "gate": {"allowed": gate_allowed},
        "backend": "cognee",
        "search_type": (search_type or memory.config.search_type).upper(),
        "available": memory.config.enabled,
        "error": None,
        "candidate_count": 0,
        "token_count": 0,
        "prompt_block": None,
        "candidates": [],
    }
    if not gate_allowed:
        return response
    result = memory.recall(clean_query, search_type=search_type)
    block = result.to_context_block(memory.config.retrieval_token_budget)
    response.update(
        {
            "search_type": result.search_type,
            "available": result.available,
            "error": truncate_preview(result.error, 240) if result.error else None,
            "candidate_count": len(result.memories),
            "token_count": max(0, len(block) // 4),
            "prompt_block": redact_prompt_block(block) if include_prompt_block and block else None,
        }
    )
    if include_candidates:
        capped = min(max(0, int(max_candidates)), 100)
        response["candidates"] = [
            {"rank": index + 1, "content_preview": truncate_preview(item.content, 240)}
            for index, item in enumerate(result.memories[:capped])
        ]
    return response


def redact_prompt_block(block_text: str) -> Dict[str, Any]:
    return {"preview": truncate_preview(block_text, 1200), "redacted": True}


def get_observability_overview(db_path: Optional[Path] = None) -> Dict[str, Any]:
    health = get_memory_health_summary(db_path=db_path)
    return {
        "health": health,
        "queue": health.get("queue", {}),
        "workers": health.get("workers", {}),
        "long_term": health.get("long_term", {}),
    }
