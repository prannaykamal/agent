from typing import Any, Dict, Optional

from src.hitl.audit_logger import log_audit_event
from src.personal_os.idempotency import make_personal_os_idempotency_key
from src.personal_os.policy import classify_personal_os_action

_SENSITIVE_KEY_PARTS = (
    "api_key",
    "token",
    "secret",
    "password",
    "credential",
    "authorization",
    "reasoning",
    "scratchpad",
    "chain_of_thought",
)


def redact_personal_os_value(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: Dict[str, Any] = {}
        for key, item in value.items():
            lower_key = str(key).lower()
            if any(part in lower_key for part in _SENSITIVE_KEY_PARTS):
                redacted[key] = "[REDACTED]"
            elif any(part in lower_key for part in ("payload", "content", "instructions", "state_json")):
                text = str(item)
                redacted[key] = text[:160] + ("..." if len(text) > 160 else "")
            else:
                redacted[key] = redact_personal_os_value(item)
        return redacted
    if isinstance(value, list):
        return [redact_personal_os_value(item) for item in value[:25]]
    return value


def log_personal_os_action(
    *,
    tool_name: str,
    action: str,
    payload: Optional[Dict[str, Any]] = None,
    target_resource: str = "",
    session_id: str = "personal_os",
    details: str = "",
) -> Dict[str, Any]:
    policy = classify_personal_os_action(tool_name)
    safe_payload = redact_personal_os_value(payload or {})
    idempotency_key = make_personal_os_idempotency_key(
        tool_name=tool_name,
        payload=safe_payload if isinstance(safe_payload, dict) else {},
        target_resource=target_resource,
        session_id=session_id,
    )
    detail_text = details or policy.reason
    if idempotency_key not in detail_text:
        detail_text = f"{detail_text} | idempotency_key={idempotency_key}"
    return log_audit_event(
        session_id=session_id,
        tool_name=tool_name,
        risk_level=policy.risk_class.value,
        action=action,
        tool_args=safe_payload if isinstance(safe_payload, dict) else {},
        details=detail_text[:1000],
    )


def get_personal_os_audit_events(limit: int = 50) -> list:
    from src.db import get_connection

    safe_limit = max(1, min(int(limit or 50), 200))
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, session_id, tool_name, tool_args_json, risk_level, action, details, created_at
        FROM audit_logs
        WHERE tool_name IN (
            'create_task', 'update_task', 'cancel_task', 'spawn_agent', 'terminate_agent',
            'pause_agent', 'resume_agent', 'schedule_job', 'cancel_job', 'lock_resource',
            'unlock_resource', 'publish_event', 'checkpoint', 'restore_checkpoint'
        )
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (safe_limit,),
    )
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows
