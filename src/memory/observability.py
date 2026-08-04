from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from langchain_core.messages import HumanMessage

from src.db import get_connection
from src.memory.context_assembler import ContextAssemblyOptions, assemble_retrieved_memory_context
from src.memory.retrieval_gate import should_retrieve_memory
from src.memory.retrieval_planner import build_retrieval_plan
from src.memory.retrieval_sources import retrieve_all_sources

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
    "structured_episodes",
    "pending_fact_candidates",
    "semantic_embeddings",
    "semantic_dedup_events",
    "consolidation_runs",
    "skill_candidates",
    "skill_versions",
    "skill_usage_stats",
    "procedural_skill_approvals",
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
        semantic = get_semantic_observability(db_path=db_path, limit=5)["summary"] if "pending_fact_candidates" in tables else {}
        procedural = get_procedural_observability(db_path=db_path, limit=5)["summary"] if "skill_candidates" in tables else {}
        skills = get_skill_observability(db_path=db_path)["summary"] if "skill_versions" in tables else {}
        status = "OK"
        if missing:
            status = "ERROR"
        elif dead_letter_count or worker_summary.get("stale", 0) or queue_status.get("FAILED", 0) or semantic.get("failed", 0) or procedural.get("waiting_for_approval", 0):
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
            "semantic": semantic,
            "procedural": procedural,
            "skills": skills,
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


def get_retrieval_trace(
    *,
    query: str,
    session_id: Optional[str] = None,
    provider: Optional[str] = "openai",
    model_name: Optional[str] = "gpt-4o-mini",
    include_candidates: bool = True,
    include_prompt_block: bool = False,
    max_candidates: int = 20,
    db_path: Optional[Path] = None,
) -> Dict[str, Any]:
    del db_path
    clean_query = " ".join(str(query or "").split())
    if not clean_query:
        raise ValueError("query must be non-empty")
    gate_allowed = should_retrieve_memory(clean_query)
    messages = [HumanMessage(content=clean_query)]
    plan = build_retrieval_plan(
        query=clean_query,
        session_id=session_id,
        provider=provider,
        model_name=model_name,
        messages=messages,
        gate_allows_retrieval=gate_allowed,
        include_debug=True,
    )
    response: Dict[str, Any] = {
        "query": clean_query,
        "session_id": session_id,
        "gate": {"allowed": gate_allowed, "reason": plan.gate_reason},
        "plan": {
            "task_type": plan.task_type,
            "memory_kinds": list(plan.memory_kinds),
            "per_source_limit": plan.per_source_limit,
            "total_token_budget": plan.total_token_budget,
            "budget_by_kind": dict(plan.budget_by_kind),
        },
        "retrieval": {"source_results": [], "candidate_count": 0, "omitted_candidate_ids": []},
        "assembly": {"included_candidate_ids": [], "omitted_candidate_ids": [], "token_count": 0, "prompt_block": None},
        "candidates": [],
    }
    if not plan.should_retrieve or plan.retrieval_request is None:
        return response
    bundle = retrieve_all_sources(plan.retrieval_request)
    assembled = assemble_retrieved_memory_context(
        bundle,
        ContextAssemblyOptions(
            total_token_budget=plan.total_token_budget,
            budget_by_kind=plan.budget_by_kind,
            include_debug=True,
        ),
    )
    response["retrieval"] = {
        "source_results": [
            {
                "source_name": result.source_name,
                "memory_kind": result.memory_kind,
                "candidate_count": len(result.candidates),
                "errors": [truncate_preview(error, 240) for error in result.errors],
            }
            for result in bundle.source_results
        ],
        "candidate_count": len(bundle.candidates),
        "omitted_candidate_ids": list(bundle.omitted_candidate_ids),
    }
    response["assembly"] = {
        "included_candidate_ids": list(assembled.included_candidate_ids),
        "omitted_candidate_ids": list(assembled.omitted_candidate_ids),
        "token_count": assembled.token_count,
        "prompt_block": redact_prompt_block(assembled.block_text) if include_prompt_block and assembled.block_text else None,
    }
    if include_candidates:
        capped = min(max(0, int(max_candidates)), 100)
        response["candidates"] = [retrieval_candidate_preview(candidate) for candidate in bundle.candidates[:capped]]
    return response


def redact_prompt_block(block_text: str) -> Dict[str, Any]:
    return {"preview": truncate_preview(block_text, 1200), "redacted": True}


def retrieval_candidate_preview(candidate: Any) -> Dict[str, Any]:
    return {
        "id": candidate.id,
        "memory_kind": candidate.memory_kind,
        "title": truncate_preview(candidate.title, 120),
        "content_preview": truncate_preview(candidate.content, 240),
        "score": {"rank_score": candidate.score.rank_score, "strategy": candidate.score.strategy},
        "provenance": {
            "source_name": candidate.provenance.source_name,
            "table_name": candidate.provenance.table_name,
            "record_id": candidate.provenance.record_id,
            "created_at": candidate.provenance.created_at,
            "fields_matched": list(candidate.provenance.fields_matched),
        },
    }


def get_semantic_observability(
    *,
    db_path: Optional[Path] = None,
    session_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
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
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    candidate_rows = _rows(
        f"SELECT * FROM pending_fact_candidates{where} ORDER BY created_at DESC, id DESC LIMIT ?",
        [*params, capped_limit],
        db_path,
    )
    all_status = _rows(f"SELECT status, COUNT(*) AS count FROM pending_fact_candidates{where} GROUP BY status", params, db_path)
    status_counts = {str(row["status"]).lower(): int(row["count"] or 0) for row in all_status}
    candidates = [
        {
            "id": row.get("id"),
            "session_id": row.get("session_id"),
            "status": row.get("status"),
            "source": row.get("source"),
            "fact_preview": truncate_preview(row.get("fact") or "", 240),
            "category": row.get("category"),
            "confidence": row.get("confidence"),
            "explicit": bool(row.get("explicit")),
            "source_job_id": row.get("source_job_id") or (safe_json_loads(row.get("metadata_json"), {}) or {}).get("source_job_id"),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        }
        for row in candidate_rows
    ]
    runs = _rows("SELECT * FROM consolidation_runs WHERE consolidation_type = 'semantic' ORDER BY created_at DESC, id DESC LIMIT ?", [min(capped_limit, 50)], db_path)
    dedup_events = _rows("SELECT * FROM semantic_dedup_events ORDER BY created_at DESC, id DESC LIMIT ?", [min(capped_limit, 50)], db_path)
    recent_runs = []
    for row in runs:
        metrics = safe_json_loads(row.get("metrics_json"), {}) or {}
        recent_runs.append(
            {
                "id": row.get("id"),
                "status": row.get("status"),
                "trigger_type": row.get("trigger_type"),
                "source_job_id": row.get("source_job_id"),
                "candidate_count": metrics.get("candidate_count") or metrics.get("claimed_count"),
                "promoted_count": metrics.get("promoted_count"),
                "discarded_count": metrics.get("discarded_count"),
                "deferred_count": metrics.get("deferred_count"),
                "created_at": row.get("created_at"),
                "updated_at": row.get("updated_at"),
            }
        )
    recent_dedup = [
        {
            "id": row.get("id"),
            "action": row.get("action"),
            "target_fact_id": row.get("target_fact_id"),
            "candidate_id": row.get("candidate_id"),
            "created_at": row.get("created_at"),
        }
        for row in dedup_events
    ]
    return {
        "summary": {
            "pending": status_counts.get("pending", 0),
            "pending_candidates": status_counts.get("pending", 0),
            "in_consolidation": status_counts.get("in_consolidation", 0),
            "promoted": status_counts.get("promoted", 0),
            "discarded": status_counts.get("discarded", 0),
            "deferred": status_counts.get("deferred", 0),
            "failed": status_counts.get("failed", 0),
            "dedup_events": _count("semantic_dedup_events", db_path),
            "consolidation_runs": _count("consolidation_runs", db_path),
            "permanent_facts": _count("facts", db_path),
        },
        "candidates": candidates,
        "recent_consolidation_runs": recent_runs,
        "recent_dedup_events": recent_dedup,
    }


def get_procedural_observability(
    *,
    db_path: Optional[Path] = None,
    status: Optional[str] = None,
    limit: int = 100,
) -> Dict[str, Any]:
    capped_limit = min(max(1, int(limit)), 200)
    where = " WHERE status = ?" if status else ""
    params: List[Any] = [status] if status else []
    rows = _rows(f"SELECT * FROM skill_candidates{where} ORDER BY updated_at DESC, id DESC LIMIT ?", [*params, capped_limit], db_path)
    status_rows = _rows(f"SELECT status, COUNT(*) AS count FROM skill_candidates{where} GROUP BY status", params, db_path)
    status_counts = {str(row["status"]).lower(): int(row["count"] or 0) for row in status_rows}
    candidates = []
    for row in rows:
        candidates.append(
            {
                "id": row.get("id"),
                "title": row.get("title"),
                "description_preview": truncate_preview(row.get("description") or "", 180),
                "status": row.get("status"),
                "workflow_category": row.get("workflow_category"),
                "confidence": row.get("confidence"),
                "occurrences": row.get("occurrences"),
                "preferred_tools": safe_json_loads(row.get("preferred_tools_json"), []),
                "tags": safe_json_loads(row.get("tags_json"), []),
                "dedup_group_id": row.get("dedup_group_id"),
                "source_episode_ids": safe_json_loads(row.get("source_episode_ids_json"), []),
                "created_at": row.get("created_at"),
                "updated_at": row.get("updated_at"),
            }
        )
    approvals = _rows(
        """
        SELECT psa.*, ar.status AS approval_request_status
        FROM procedural_skill_approvals psa
        LEFT JOIN approval_requests ar ON ar.id = psa.approval_request_id
        ORDER BY psa.created_at DESC, psa.id DESC
        LIMIT ?
        """,
        [min(capped_limit, 100)],
        db_path,
    )
    approval_items = [
        {
            "id": row.get("id"),
            "candidate_id": row.get("candidate_id"),
            "approval_request_id": row.get("approval_request_id"),
            "approval_request_status": row.get("approval_request_status"),
            "status": row.get("status"),
            "action": row.get("action"),
            "skill_version_id": row.get("skill_version_id"),
            "created_at": row.get("created_at"),
            "decided_at": row.get("decided_at"),
        }
        for row in approvals
    ]
    return {
        "summary": {
            "new": status_counts.get("new", 0),
            "observing": status_counts.get("observing", 0),
            "ready_for_promotion": status_counts.get("ready_for_promotion", 0),
            "waiting_for_approval": status_counts.get("waiting_for_approval", 0),
            "promoted": status_counts.get("promoted", 0),
            "rejected": status_counts.get("rejected", 0),
            "approvals_pending": len([item for item in approval_items if item["status"] == "PENDING"]),
        },
        "candidates": candidates,
        "approvals": approval_items,
    }


def get_skill_observability(*, db_path: Optional[Path] = None, include_archived: bool = False) -> Dict[str, Any]:
    where = "" if include_archived else " WHERE archived_at IS NULL"
    versions = _rows(f"SELECT * FROM skill_versions{where} ORDER BY active DESC, name ASC, version DESC", db_path=db_path)
    usage_rows = _rows("SELECT * FROM skill_usage_stats", db_path=db_path)
    usage_by_skill = {str(row["skill_id"]): row for row in usage_rows}
    active_versions = []
    disabled = 0
    archived = 0
    for row in versions:
        if not row.get("enabled"):
            disabled += 1
        if row.get("archived_at"):
            archived += 1
        if row.get("active") and row.get("enabled"):
            usage = usage_by_skill.get(str(row.get("skill_id")), {})
            active_versions.append(
                {
                    "id": row.get("id"),
                    "skill_id": row.get("skill_id"),
                    "version": row.get("version"),
                    "name": row.get("name"),
                    "description": row.get("description"),
                    "enabled": bool(row.get("enabled")),
                    "active": bool(row.get("active")),
                    "author": row.get("author"),
                    "approval_required": bool(row.get("approval_required")),
                    "approval_id": row.get("approval_id"),
                    "candidate_id": row.get("candidate_id"),
                    "confidence": row.get("confidence"),
                    "file_path": _safe_skill_path(row.get("file_path")),
                    "content_hash": row.get("content_hash"),
                    "created_at": row.get("created_at"),
                    "approved_at": row.get("approved_at"),
                    "usage": {
                        "times_loaded": int(usage.get("times_loaded") or 0),
                        "times_used": int(usage.get("times_used") or 0),
                        "last_loaded": usage.get("last_loaded"),
                        "last_used": usage.get("last_used"),
                    },
                }
            )
    return {
        "summary": {
            "active_versions": len(active_versions),
            "disabled_versions": disabled,
            "archived_versions": archived,
            "total_times_loaded": sum(int(row.get("times_loaded") or 0) for row in usage_rows),
            "total_times_used": sum(int(row.get("times_used") or 0) for row in usage_rows),
            "snapshot_loaded_at": None,
            "snapshot_skill_count": 0,
        },
        "active_versions": active_versions,
        "snapshot": {"loaded_at": None, "skill_count": 0, "last_error": None},
    }


def _safe_skill_path(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value)
    marker = ".agent"
    if marker in text:
        return text[text.index(marker) :]
    return truncate_preview(text, 180)


def get_observability_overview(db_path: Optional[Path] = None) -> Dict[str, Any]:
    health = get_memory_health_summary(db_path=db_path)
    return {
        "health": health,
        "queue": health.get("queue", {}),
        "workers": health.get("workers", {}),
        "semantic": health.get("semantic", {}),
        "procedural": health.get("procedural", {}),
        "skills": health.get("skills", {}),
    }
