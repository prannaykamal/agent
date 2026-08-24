"""Bind email_send to the last Gmail draft so confirmations cannot invent a recipient."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from src.hitl.approval_engine import match_chat_approval_decision

_PLACEHOLDER_DOMAINS = frozenset(
    {
        "example.com",
        "example.org",
        "example.net",
        "email.com",
        "test.com",
        "localhost",
    }
)
_DRAFT_RESULT_RE = re.compile(
    r"Created Gmail draft (?P<draft_id>\S+) to (?P<to>[^\s]+@[^\s]+?)(?:\. Message id|\.\s*$)",
    re.IGNORECASE,
)
_PLACEHOLDER_BODY_MARKERS = ("[your name]", "[name]", "your name here")


def _first_email(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        for item in value:
            text = _first_email(item)
            if text:
                return text
        return ""
    text = str(value or "").strip()
    if text.startswith("[") and text.endswith("]"):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, (list, tuple, str)):
            return _first_email(parsed)
    return text


def _emails_equal(left: str, right: str) -> bool:
    return _first_email(left).lower() == _first_email(right).lower() and bool(_first_email(left))


def is_placeholder_recipient(value: Any) -> bool:
    email = _first_email(value)
    if not email or "@" not in email:
        return True
    domain = email.rsplit("@", 1)[-1].lower().strip(" >")
    return domain in _PLACEHOLDER_DOMAINS


def _is_placeholder_body(value: Any) -> bool:
    body = str(value or "").lower()
    return any(marker in body for marker in _PLACEHOLDER_BODY_MARKERS)


def _draft_from_args(args: Any) -> Dict[str, str]:
    payload = dict(args or {}) if isinstance(args, dict) else {}
    to = _first_email(payload.get("to") or payload.get("recipient"))
    return {
        "to": to,
        "subject": str(payload.get("subject") or "").strip(),
        "body": str(payload.get("body") or ""),
        "draft_id": str(payload.get("draft_id") or "").strip(),
    }


def _draft_from_result_text(text: Any) -> Dict[str, str]:
    match = _DRAFT_RESULT_RE.search(str(text or ""))
    if not match:
        return {}
    return {
        "to": str(match.group("to") or "").strip().rstrip("."),
        "subject": "",
        "body": "",
        "draft_id": str(match.group("draft_id") or "").strip(),
    }


def _merge_draft(base: Dict[str, str], incoming: Dict[str, str]) -> Dict[str, str]:
    merged = dict(base)
    for key, value in incoming.items():
        if str(value or "").strip():
            merged[key] = value
    return merged


def _tool_name(call: Any) -> str:
    if isinstance(call, dict):
        return str(call.get("name") or "")
    return str(getattr(call, "name", "") or "")


def _tool_args(call: Any) -> Dict[str, Any]:
    if isinstance(call, dict):
        return dict(call.get("args") or {})
    return dict(getattr(call, "args", None) or {})


def last_gmail_draft_from_messages(messages: Optional[Sequence[Any]]) -> Dict[str, str]:
    draft: Dict[str, str] = {}
    for message in messages or []:
        content = getattr(message, "content", "")
        name = str(getattr(message, "name", "") or "")
        if name == "email_draft" or "Created Gmail draft" in str(content):
            draft = _merge_draft(draft, _draft_from_result_text(content))
        for call in getattr(message, "tool_calls", None) or []:
            if _tool_name(call) == "email_draft":
                draft = _merge_draft(draft, _draft_from_args(_tool_args(call)))
    return draft if draft.get("to") or draft.get("draft_id") else {}


def last_gmail_draft_from_session(session_id: str, db_path: Optional[Path] = None) -> Dict[str, str]:
    if not session_id:
        return {}
    try:
        from src.db import get_connection

        conn = get_connection(db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT tool_args FROM tool_calls
            WHERE session_id = ? AND tool_name = 'email_draft'
            ORDER BY created_at DESC LIMIT 1
            """,
            (session_id,),
        )
        args_row = cursor.fetchone()
        cursor.execute(
            """
            SELECT result_content FROM tool_results
            WHERE session_id = ? AND tool_name = 'email_draft'
            ORDER BY created_at DESC LIMIT 1
            """,
            (session_id,),
        )
        result_row = cursor.fetchone()
        conn.close()
    except Exception:
        return {}

    draft: Dict[str, str] = {}
    if args_row:
        raw_args = args_row[0] if not isinstance(args_row, dict) else args_row.get("tool_args")
        try:
            parsed = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
        except Exception:
            parsed = {}
        draft = _merge_draft(draft, _draft_from_args(parsed))
    if result_row:
        raw_result = result_row[0] if not isinstance(result_row, dict) else result_row.get("result_content")
        draft = _merge_draft(draft, _draft_from_result_text(raw_result))
    return draft if draft.get("to") or draft.get("draft_id") else {}


def last_gmail_draft(
    messages: Optional[Sequence[Any]] = None,
    *,
    session_id: str = "",
    db_path: Optional[Path] = None,
) -> Dict[str, str]:
    return last_gmail_draft_from_messages(messages) or last_gmail_draft_from_session(session_id, db_path=db_path)


def should_bind_email_send(args: Optional[Dict[str, Any]], draft: Dict[str, str], last_user_text: str = "") -> bool:
    if not draft.get("to") and not draft.get("draft_id"):
        return False
    if match_chat_approval_decision(last_user_text) == "APPROVED":
        return True
    requested_to = _first_email((args or {}).get("to") or (args or {}).get("recipient"))
    if is_placeholder_recipient(requested_to):
        return True
    if _is_placeholder_body((args or {}).get("body")) and draft.get("body"):
        return True
    if requested_to and draft.get("to") and not _emails_equal(requested_to, draft["to"]) and is_placeholder_recipient(requested_to):
        return True
    return False


def bind_email_send_args(
    args: Optional[Dict[str, Any]],
    *,
    messages: Optional[Sequence[Any]] = None,
    last_user_text: str = "",
    session_id: str = "",
    db_path: Optional[Path] = None,
) -> Dict[str, Any]:
    bound = dict(args or {})
    draft = last_gmail_draft(messages, session_id=session_id, db_path=db_path)
    if not should_bind_email_send(bound, draft, last_user_text):
        return bound
    if draft.get("to"):
        bound["to"] = draft["to"]
    if draft.get("subject"):
        bound["subject"] = draft["subject"]
    if draft.get("body"):
        bound["body"] = draft["body"]
    if draft.get("draft_id"):
        bound["draft_id"] = draft["draft_id"]
    return bound
