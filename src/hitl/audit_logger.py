import uuid
import json
from typing import Dict, Any, Optional
from pathlib import Path
from src.db import get_connection

def log_audit_event(
    session_id: str,
    tool_name: str,
    risk_level: str,
    action: str,
    tool_args: Optional[Dict[str, Any]] = None,
    details: str = "",
    db_path: Optional[Path] = None
) -> Dict[str, Any]:
    """
    Records an audit log entry for Medium or High risk operations.
    """
    audit_id = f"aud_{uuid.uuid4().hex[:8]}"
    args_json = json.dumps(tool_args) if tool_args else "{}"

    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO audit_logs (id, session_id, tool_name, tool_args_json, risk_level, action, details, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
        """,
        (audit_id, session_id, tool_name, args_json, risk_level, action, details)
    )
    conn.commit()
    conn.close()

    return {
        "id": audit_id,
        "session_id": session_id,
        "tool_name": tool_name,
        "risk_level": risk_level,
        "action": action,
        "details": details
    }
