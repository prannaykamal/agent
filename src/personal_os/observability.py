from typing import Any, Dict, List

from src.db import get_connection
from src.personal_os.audit import get_personal_os_audit_events
from src.personal_os.policy import classify_personal_os_action


def _count_table(table_name: str, status_column: str = "") -> Dict[str, Any]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(f"SELECT COUNT(*) AS count FROM {table_name}")
    total = int(cursor.fetchone()["count"])
    by_status: Dict[str, int] = {}
    if status_column:
        cursor.execute(f"SELECT {status_column} AS status, COUNT(*) AS count FROM {table_name} GROUP BY {status_column}")
        by_status = {str(row["status"]): int(row["count"]) for row in cursor.fetchall()}
    conn.close()
    return {"total": total, "by_status": by_status}


def get_personal_os_status() -> Dict[str, Any]:
    return {
        "provider": "personal_os",
        "implementation_type": "local",
        "status": "available",
        "responsibilities": [
            "local task state",
            "local sub-agent state inspection/control",
            "HITL checkpoint metadata",
            "local resource locks",
            "bounded local audit",
            "health/readiness",
        ],
        "non_responsibilities": [
            "provider-managed email, chat, calendar, or search calls",
            "arbitrary browsing",
            "arbitrary code execution",
            "schedule recurrence ownership",
            "direct memory table writes",
        ],
        "tasks": _count_table("tasks", "status"),
        "sub_agents": _count_table("sub_agents", "status"),
        "resource_locks": _count_table("resource_locks"),
        "checkpoints": _count_table("checkpoints", "status"),
        "scheduled_jobs_boundary": _count_table("scheduled_jobs", "status"),
    }


def get_personal_os_actions() -> List[Dict[str, Any]]:
    from src.personal_os.registry import get_personal_os_tool_metadata

    actions = []
    for item in get_personal_os_tool_metadata(include_deprecated=True):
        policy = classify_personal_os_action(item.legacy_name)
        action = item.to_dict()
        action["policy"] = policy.to_dict()
        actions.append(action)
    return actions


def get_personal_os_audit(limit: int = 50) -> Dict[str, Any]:
    events = get_personal_os_audit_events(limit=limit)
    return {
        "audit_events": events,
        "total_events": len(events),
    }
