import uuid
import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from src.db import get_connection

def generate_payload_preview(tool_name: str, tool_args: Dict[str, Any]) -> str:
    """Generates a rich, human-readable preview summary for approval requests."""
    tname = tool_name.strip().lower()
    if tname in ("email_send", "send_email"):
        to = tool_args.get("recipient") or tool_args.get("to") or "Unknown"
        subj = tool_args.get("subject") or "No Subject"
        body = tool_args.get("body") or ""
        return f"[Email Preview] To: {to} | Subject: {subj}\nBody: {body[:200]}"

    if tname in ("whatsapp_send", "telegram_send"):
        to = tool_args.get("recipient") or tool_args.get("chat_id") or "Unknown"
        msg = tool_args.get("message") or ""
        return f"[{tname.upper()} Preview] To/Chat: {to}\nMessage: {msg[:200]}"

    if tname in ("calendar_create_event", "calendar_delete_event"):
        title = tool_args.get("title") or tool_args.get("event_id") or "Event"
        start = tool_args.get("start_time") or ""
        end = tool_args.get("end_time") or ""
        return f"[Calendar Preview] Action: {tname} | Event: '{title}' ({start} - {end})"

    if tname == "github_merge":
        src = tool_args.get("source_branch") or "feature"
        tgt = tool_args.get("target_branch") or "main"
        return f"[GitHub Merge Preview] Source: '{src}' ➔ Target: '{tgt}'"

    return f"[{tool_name} Preview] Payload: {json.dumps(tool_args)}"

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
    return [dict(r) for r in rows]

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
    return dict(row) if row else None

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

