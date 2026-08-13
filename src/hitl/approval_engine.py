import uuid
import json
import re
from pathlib import Path
from typing import List, Dict, Any, Optional
from src.db import get_connection
from src.tools.removed_tools import is_removed_tool_name, get_removed_tool_blocked_message

_AFFIRM_PHRASES = {
    "yes", "y", "yeah", "yep", "ok", "okay", "sure", "go ahead",
    "send", "send it", "send now", "please send", "please send it",
    "approve", "approved", "proceed", "do it", "confirm",
    "yes please", "yes send", "yes send it", "yes go ahead",
    "ok send", "ok send it", "okay send it",
}
_REJECT_PHRASES = {
    "no", "n", "nope", "cancel", "reject", "rejected",
    "dont", "do not", "stop", "never", "no thanks",
}


def match_chat_approval_decision(text: str) -> Optional[str]:
    """Map a short chat reply to APPROVED/REJECTED when the user is confirming HITL."""
    raw = str(text or "").strip().lower()
    if not raw or len(raw) > 48:
        return None
    cleaned = re.sub(r"[^\w\s']+", " ", raw)
    cleaned = re.sub(r"\s+", " ", cleaned).replace("'", "").strip()
    if cleaned in _AFFIRM_PHRASES:
        return "APPROVED"
    if cleaned in _REJECT_PHRASES:
        return "REJECTED"
    return None

def generate_payload_preview(tool_name: str, tool_args: Dict[str, Any]) -> str:
    """Generates a rich, human-readable preview summary for approval requests."""
    raw = dict(tool_args or {})
    batch = raw.get("_batch_calls")
    public = {key: value for key, value in raw.items() if not str(key).startswith("_")}
    prefix = ""
    if isinstance(batch, list) and len(batch) > 1:
        prefix = f"[Batch of {len(batch)} '{tool_name}' actions]\n"
    tname = tool_name.strip().lower()
    if tname in ("email_send", "send_email"):
        to = public.get("recipient") or public.get("to") or "Unknown"
        subj = public.get("subject") or "No Subject"
        body = public.get("body") or ""
        return prefix + f"[Email Preview] To: {to} | Subject: {subj}\nBody: {body[:200]}"

    if tname in ("whatsapp_send", "telegram_send"):
        to = public.get("recipient") or public.get("chat_id") or "Unknown"
        msg = public.get("message") or ""
        return prefix + f"[{tname.upper()} Preview] To/Chat: {to}\nMessage: {msg[:200]}"

    if tname in ("calendar_create_event", "calendar_delete_event"):
        title = public.get("title") or public.get("event_id") or "Event"
        start = public.get("start_time") or ""
        end = public.get("end_time") or ""
        return prefix + f"[Calendar Preview] Action: {tname} | Event: '{title}' ({start} - {end})"

    return prefix + f"[{tool_name} Preview] Payload: {json.dumps(public)}"

def create_approval_request(
    session_id: str,
    tool_name: str,
    tool_args: Dict[str, Any],
    reason: str,
    checkpoint_id: str = "",
    idempotency_key: Optional[str] = None,
    db_path: Optional[Path] = None
) -> Dict[str, Any]:
    """Creates a pending HITL approval request record with payload preview and optional idempotency_key in SQLite."""
    key = idempotency_key or f"idem_{uuid.uuid4().hex[:12]}"
    conn = get_connection(db_path)
    cursor = conn.cursor()

    # Check for duplicate idempotency key
    if idempotency_key:
        try:
            cursor.execute("SELECT * FROM approval_requests WHERE idempotency_key = ?", (idempotency_key,))
            existing = cursor.fetchone()
            if existing:
                conn.close()
                row_dict = dict(existing)
                row_dict["request_id"] = row_dict["id"]
                return row_dict
        except Exception:
            pass

    request_id = f"req_{uuid.uuid4().hex[:8]}"
    args_json = json.dumps(tool_args)
    preview = generate_payload_preview(tool_name, tool_args)

    try:
        cursor.execute(
            """
            INSERT INTO approval_requests (id, session_id, tool_name, tool_args_json, risk_level, reason, status, checkpoint_id, idempotency_key, execution_status, created_at)
            VALUES (?, ?, ?, ?, 'High', ?, 'PENDING', ?, ?, 'PENDING', datetime('now'))
            """,
            (request_id, session_id, tool_name, args_json, f"{reason}\n{preview}", checkpoint_id, key)
        )
    except Exception:
        cursor.execute(
            """
            INSERT INTO approval_requests (id, session_id, tool_name, tool_args_json, risk_level, reason, status, checkpoint_id, created_at)
            VALUES (?, ?, ?, ?, 'High', ?, 'PENDING', ?, datetime('now'))
            """,
            (request_id, session_id, tool_name, args_json, f"{reason}\n{preview}", checkpoint_id)
        )

    conn.commit()
    conn.close()

    # Log audit event for high risk approval creation
    try:
        from src.hitl.audit_logger import log_audit_event
        log_audit_event(
            session_id=session_id,
            tool_name=tool_name,
            risk_level="High",
            action="HITL_REQUEST_CREATED",
            tool_args=tool_args,
            details=f"Approval request {request_id} created (idempotency_key={key})",
            db_path=db_path
        )
    except Exception:
        pass

    return {
        "request_id": request_id,
        "session_id": session_id,
        "tool_name": tool_name,
        "tool_args": tool_args,
        "risk_level": "High",
        "reason": f"{reason}\n{preview}",
        "preview": preview,
        "status": "PENDING",
        "checkpoint_id": checkpoint_id,
        "idempotency_key": key
    }

def get_pending_approvals(
    session_id: Optional[str] = None,
    db_path: Optional[Path] = None
) -> List[Dict[str, Any]]:
    """Returns all pending approval requests."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    if session_id:
        cursor.execute("SELECT * FROM approval_requests WHERE status = 'PENDING' AND session_id = ? ORDER BY created_at DESC", (session_id,))
    else:
        cursor.execute("SELECT * FROM approval_requests WHERE status = 'PENDING' ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()
    return [_serialize_approval_row(row) for row in rows]


def _serialize_approval_row(row: Any) -> Dict[str, Any]:
    payload = dict(row)
    payload["request_id"] = payload.get("id") or payload.get("request_id")
    raw_args = payload.get("tool_args_json") or payload.get("tool_args") or "{}"
    if isinstance(raw_args, str):
        try:
            payload["tool_args"] = json.loads(raw_args)
        except Exception:
            payload["tool_args"] = {}
    elif not isinstance(payload.get("tool_args"), dict):
        payload["tool_args"] = {}
    return payload

def get_all_approval_requests(db_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Alias for get_pending_approvals returning all pending approval requests."""
    return get_pending_approvals(db_path=db_path)

def get_approval_request(
    request_id: str,
    db_path: Optional[Path] = None
) -> Optional[Dict[str, Any]]:
    """Retrieves an approval request record by ID."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM approval_requests WHERE id = ?", (request_id,))
    row = cursor.fetchone()
    conn.close()
    return _serialize_approval_row(row) if row else None

def process_approval_decision(
    request_id: str,
    decision: str,
    idempotency_key: Optional[str] = None,
    db_path: Optional[Path] = None
) -> Dict[str, Any]:
    """Processes approval decision ('APPROVED' or 'REJECTED') with idempotency and duplicate execution protection."""
    norm_decision = decision.upper().strip()
    if norm_decision not in ("APPROVED", "REJECTED"):
        raise ValueError("Decision must be either 'APPROVED' or 'REJECTED'")

    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM approval_requests WHERE id = ?", (request_id,))
    row = cursor.fetchone()

    if not row:
        conn.close()
        raise ValueError(f"Approval request '{request_id}' not found.")

    existing_status = row["status"]
    if norm_decision == "APPROVED" and is_removed_tool_name(row["tool_name"]):
        blocked_message = get_removed_tool_blocked_message(row["tool_name"])
        try:
            cursor.execute(
                """
                UPDATE approval_requests
                SET status = 'REJECTED', execution_status = 'BLOCKED'
                WHERE id = ?
                """,
                (request_id,),
            )
        except Exception:
            cursor.execute(
                """
                UPDATE approval_requests
                SET status = 'REJECTED'
                WHERE id = ?
                """,
                (request_id,),
            )
        conn.commit()
        conn.close()
        try:
            from src.hitl.audit_logger import log_audit_event
            log_audit_event(
                session_id=row["session_id"],
                tool_name=row["tool_name"],
                risk_level="Blocked",
                action="REMOVED_TOOL_APPROVAL_BLOCKED",
                details=blocked_message,
                db_path=db_path,
            )
        except Exception:
            pass
        raise ValueError(blocked_message)

    if existing_status in ("APPROVED", "REJECTED", "EXECUTED"):
        conn.close()

        # Log audit log for blocked duplicate approval attempt
        try:
            from src.hitl.audit_logger import log_audit_event
            log_audit_event(
                session_id=row["session_id"],
                tool_name=row["tool_name"],
                risk_level=row["risk_level"],
                action="DUPLICATE_APPROVAL_BLOCKED",
                details=f"Blocked duplicate approval attempt for request {request_id} (current status: {existing_status})",
                db_path=db_path
            )
        except Exception:
            pass

        raise ValueError(f"Approval request '{request_id}' has already been processed with status '{existing_status}'. Duplicate execution blocked.")

    try:
        cursor.execute(
            """
            UPDATE approval_requests
            SET status = ?, execution_status = ?
            WHERE id = ?
            """,
            (norm_decision, f"{norm_decision}_EXECUTED", request_id)
        )
    except Exception:
        cursor.execute(
            """
            UPDATE approval_requests
            SET status = ?
            WHERE id = ?
            """,
            (norm_decision, request_id)
        )

    conn.commit()

    cursor.execute("SELECT * FROM approval_requests WHERE id = ?", (request_id,))
    updated_row = cursor.fetchone()
    conn.close()

    # Log audit event for decision and tool execution
    try:
        from src.hitl.audit_logger import log_audit_event
        log_audit_event(
            session_id=row["session_id"],
            tool_name=row["tool_name"],
            risk_level=row["risk_level"],
            action=f"HITL_{norm_decision}",
            details=f"Operator decided {norm_decision} for request {request_id}",
            db_path=db_path
        )
        if norm_decision == "APPROVED":
            log_audit_event(
                session_id=row["session_id"],
                tool_name=row["tool_name"],
                risk_level=row["risk_level"],
                action="HIGH_RISK_TOOL_EXECUTED",
                details=f"High risk tool {row['tool_name']} executed following human approval.",
                db_path=db_path
            )
    except Exception:
        pass

    return dict(updated_row)

