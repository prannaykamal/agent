from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional

from src.db import get_connection
from src.tools.policy import ToolCallerSource, evaluate_tool_policy
from src.tools.registry import get_all_tool_metadata_for_policy, get_bindable_tool_metadata
from src.tools.removed_tools import get_removed_tool_metadata, is_removed_tool_name


SECRET_KEY_MARKERS = (
    "api_key",
    "token",
    "secret",
    "password",
    "credential",
    "authorization",
    "access_token",
    "refresh_token",
)

HIDDEN_REASONING_MARKERS = (
    "chain_of_thought",
    "scratchpad",
    "hidden_reasoning",
)

PREVIEW_KEY_MARKERS = (
    "prompt",
    "message",
    "messages",
    "body",
    "conversation",
    "provider_payload",
    "tool_args",
    "payload",
    "rationale",
    "reasoning",
    "result_content",
    "details",
)


def truncate_preview(value: Any, *, limit: int = 160) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def safe_json_loads(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if value is None:
        return None
    try:
        return json.loads(str(value))
    except Exception:
        return value


def _key_has_marker(key: str, markers: Iterable[str]) -> bool:
    lower = str(key or "").lower()
    return any(marker in lower for marker in markers)


def redact_observability_value(value: Any, *, key: str = "", preview_limit: int = 160) -> Any:
    if _key_has_marker(key, SECRET_KEY_MARKERS) or _key_has_marker(key, HIDDEN_REASONING_MARKERS):
        return "[REDACTED]"
    if _key_has_marker(key, PREVIEW_KEY_MARKERS):
        parsed = safe_json_loads(value)
        if isinstance(parsed, dict):
            return {
                str(child_key): redact_observability_value(child_value, key=str(child_key), preview_limit=preview_limit)
                for child_key, child_value in parsed.items()
            }
        if isinstance(parsed, list):
            return [redact_observability_value(item, preview_limit=preview_limit) for item in parsed]
        return {"preview": truncate_preview(value, limit=preview_limit), "truncated": len(str(value or "")) > preview_limit}
    if isinstance(value, dict):
        return {
            str(child_key): redact_observability_value(child_value, key=str(child_key), preview_limit=preview_limit)
            for child_key, child_value in value.items()
        }
    if isinstance(value, list):
        return [redact_observability_value(item, key=key, preview_limit=preview_limit) for item in value]
    return value


def redact_observability_payload(payload: Any, *, preview_limit: int = 160) -> Any:
    return redact_observability_value(safe_json_loads(payload), preview_limit=preview_limit)


def _table_exists(table_name: str) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name = ?", (table_name,))
    exists = cursor.fetchone() is not None
    conn.close()
    return exists


def _count_table(table_name: str, status_column: str = "") -> Dict[str, Any]:
    if not _table_exists(table_name):
        return {"total": 0, "by_status": {}, "present": False}
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(f"SELECT COUNT(*) AS count FROM {table_name}")
    total = int(cursor.fetchone()["count"])
    by_status: Dict[str, int] = {}
    if status_column:
        cursor.execute(f"SELECT {status_column} AS status, COUNT(*) AS count FROM {table_name} GROUP BY {status_column}")
        by_status = {str(row["status"]): int(row["count"]) for row in cursor.fetchall()}
    conn.close()
    return {"total": total, "by_status": by_status, "present": True}


def _list_rows(table_name: str, *, order_by: str = "created_at", limit: int = 50, where: str = "", params: tuple[Any, ...] = ()) -> List[Dict[str, Any]]:
    if not _table_exists(table_name):
        return []
    safe_limit = max(1, min(int(limit or 50), 200))
    conn = get_connection()
    cursor = conn.cursor()
    query = f"SELECT * FROM {table_name}"
    if where:
        query += f" WHERE {where}"
    query += f" ORDER BY {order_by} DESC LIMIT ?"
    cursor.execute(query, (*params, safe_limit))
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


def _redact_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [redact_observability_value(row) for row in rows]


def _metadata_group(item: Dict[str, Any]) -> str:
    if item.get("implementation_type") == "removed":
        return "removed"
    if item.get("provider") == "personal_os" and item.get("category") == "scheduler_boundary":
        return "cron"
    if item.get("provider") == "personal_os":
        return "personal_os"
    if item.get("implementation_type") == "mcp":
        return "mcp"
    if item.get("implementation_type") == "external_api":
        return "external_api"
    return "other"


def get_tool_registry_observability() -> Dict[str, Any]:
    metadata = [item.to_dict() for item in get_all_tool_metadata_for_policy()]
    bindable_names = {item.legacy_name for item in get_bindable_tool_metadata()}
    grouped: Dict[str, List[Dict[str, Any]]] = {"personal_os": [], "cron": [], "mcp": [], "external_api": [], "removed": [], "other": []}
    for item in metadata:
        item["bindable"] = item["legacy_name"] in bindable_names
        grouped.setdefault(_metadata_group(item), []).append(redact_observability_value(item))
    return {
        "total_metadata_entries": len(metadata),
        "total_bindable_tools": len(bindable_names),
        "groups": grouped,
        "group_counts": {key: len(value) for key, value in grouped.items()},
    }


def get_policy_matrix_observability() -> Dict[str, Any]:
    entries = []
    counts: Dict[str, int] = {}
    for metadata in get_all_tool_metadata_for_policy():
        decision = evaluate_tool_policy(metadata.legacy_name, {}, source=ToolCallerSource.API, metadata=metadata)
        row = {
            "tool_id": metadata.tool_id,
            "legacy_name": metadata.legacy_name,
            "provider": metadata.provider,
            "implementation_type": metadata.implementation_type.value,
            "availability_status": metadata.availability_status.value,
            "risk_class": metadata.risk_class.value,
            "approval_policy": metadata.approval_policy.value,
            "policy_decision": decision.decision.value,
            "reason_code": decision.reason_code,
            "read_write_capability": metadata.read_write_capability.value,
            "external_side_effect": metadata.external_side_effect,
            "destructive": metadata.destructive,
            "provider_managed": metadata.provider_managed,
        }
        entries.append(row)
        counts[row["policy_decision"]] = counts.get(row["policy_decision"], 0) + 1
    return {"entries": entries, "decision_counts": counts}


def get_provider_status_observability() -> Dict[str, Any]:
    from src.external_providers.registry import get_external_provider_statuses
    from src.tools.mcp_provider_registry import get_mcp_provider_statuses

    mcp_providers = get_mcp_provider_statuses(include_config=False, refresh=False)
    external_providers = get_external_provider_statuses()
    all_providers = [
        {**provider, "provider_layer": "mcp"}
        for provider in mcp_providers
    ] + [
        {**provider, "provider_layer": "external_api"}
        for provider in external_providers
    ]
    return {
        "providers": redact_observability_value(all_providers),
        "mcp_providers": redact_observability_value(mcp_providers),
        "external_api_providers": redact_observability_value(external_providers),
        "total_providers": len(all_providers),
        "available_providers": sum(1 for provider in all_providers if provider.get("availability_status") in ("available", "configured")),
        "mcp_provider_count": len(mcp_providers),
        "external_api_provider_count": len(external_providers),
    }


def get_cron_observability(limit: int = 50) -> Dict[str, Any]:
    from src.personal_os.scheduler_store import ToolScheduleRepository

    repo = ToolScheduleRepository()
    schedules = [redact_observability_value(item.to_dict()) for item in repo.list_schedules(limit=limit)]
    runs = [redact_observability_value(item.to_dict()) for item in repo.list_runs(limit=limit)]
    return {
        "schedules": schedules,
        "runs": runs,
        "schedule_counts": _count_table("tool_schedules", "status"),
        "run_counts": _count_table("tool_schedule_runs", "status"),
    }


def get_tool_calls_observability(limit: int = 50) -> Dict[str, Any]:
    rows = _list_rows("tool_calls", limit=limit)
    for row in rows:
        if "tool_args" in row:
            row["tool_args"] = redact_observability_payload(row.get("tool_args"))
    return {"tool_calls": _redact_rows(rows), "total_returned": len(rows), "counts": _count_table("tool_calls", "status")}


def get_tool_results_observability(limit: int = 50) -> Dict[str, Any]:
    rows = _list_rows("tool_results", limit=limit)
    for row in rows:
        if "result_content" in row:
            row["result_content"] = redact_observability_payload(row.get("result_content"))
    return {"tool_results": _redact_rows(rows), "total_returned": len(rows), "counts": _count_table("tool_results", "status")}


def get_tool_audit_observability(limit: int = 50) -> Dict[str, Any]:
    rows = _list_rows("audit_logs", limit=limit)
    for row in rows:
        if "tool_args" in row:
            row["tool_args"] = redact_observability_payload(row.get("tool_args"))
        if "details" in row:
            row["details"] = redact_observability_payload(row.get("details"))
    return {"audit_events": _redact_rows(rows), "total_returned": len(rows), "counts": _count_table("audit_logs")}


def get_blocked_tool_observability(limit: int = 50) -> Dict[str, Any]:
    rows = _list_rows(
        "audit_logs",
        limit=limit,
        where="risk_level = ? OR action LIKE ?",
        params=("Blocked", "%BLOCKED%"),
    )
    removed_names = {item.legacy_name for item in get_removed_tool_metadata()}
    removed_rows = [row for row in rows if row.get("tool_name") in removed_names or is_removed_tool_name(str(row.get("tool_name") or "")) or row.get("risk_level") == "Blocked"]
    for row in removed_rows:
        if "tool_args" in row:
            row["tool_args"] = redact_observability_payload(row.get("tool_args"))
        if "details" in row:
            row["details"] = redact_observability_payload(row.get("details"))
    return {
        "blocked_attempts": _redact_rows(removed_rows),
        "total_returned": len(removed_rows),
        "removed_tool_names": sorted(removed_names),
    }


def get_tools_status_observability() -> Dict[str, Any]:
    registry = get_tool_registry_observability()
    providers = get_provider_status_observability()
    policy = get_policy_matrix_observability()
    return {
        "status": "OK",
        "registry": {
            "total_metadata_entries": registry["total_metadata_entries"],
            "total_bindable_tools": registry["total_bindable_tools"],
            "group_counts": registry["group_counts"],
        },
        "providers": {
            "total_providers": providers["total_providers"],
            "available_providers": providers["available_providers"],
        },
        "policy": {
            "decision_counts": policy["decision_counts"],
        },
        "removed_tools": {
            "total": len(get_removed_tool_metadata()),
            "active": 0,
        },
    }


def get_tools_observability_overview(limit: int = 20) -> Dict[str, Any]:
    return {
        "status": get_tools_status_observability(),
        "registry": get_tool_registry_observability(),
        "providers": get_provider_status_observability(),
        "policy": get_policy_matrix_observability(),
        "cron": {
            "schedule_counts": _count_table("tool_schedules", "status"),
            "run_counts": _count_table("tool_schedule_runs", "status"),
        },
        "tool_calls": get_tool_calls_observability(limit=limit),
        "tool_results": get_tool_results_observability(limit=limit),
        "audit": get_tool_audit_observability(limit=limit),
        "blocked": get_blocked_tool_observability(limit=limit),
    }

