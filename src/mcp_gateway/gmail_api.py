"""Gmail REST API helpers for the local personal-Gmail MCP server."""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from email.mime.text import MIMEText
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

GMAIL_API_ROOT = "https://gmail.googleapis.com/gmail/v1/users/me"
SIGN_IN_REQUIRED = (
    "Google sign-in required. Open Tools Ops and click Sign in with Google."
)

HttpRequestFn = Callable[[str, str, Optional[Dict[str, str]], Optional[bytes]], Dict[str, Any]]
Recipient = Union[str, Sequence[str]]


def access_token_from_env(env: Optional[Dict[str, str]] = None) -> str:
    source = env if env is not None else os.environ
    return str(
        source.get("GMAIL_ACCESS_TOKEN")
        or source.get("GOOGLE_ACCESS_TOKEN")
        or ""
    ).strip()


def normalize_recipients(to: Recipient) -> List[str]:
    if isinstance(to, str):
        values = [to]
    elif isinstance(to, Sequence):
        values = list(to)
    else:
        values = [str(to)]
    return [str(item).strip() for item in values if str(item).strip()]


def encode_raw_message(to: Recipient, subject: str, body: str) -> str:
    recipients = normalize_recipients(to)
    message = MIMEText(body or "", "plain", "utf-8")
    if recipients:
        message["To"] = ", ".join(recipients)
    message["Subject"] = str(subject or "")
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    return raw.rstrip("=")


def _default_http_request(method: str, url: str, headers: Optional[Dict[str, str]], body: Optional[bytes]) -> Dict[str, Any]:
    request = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise GmailApiError(exc.code, _error_message(exc.code, detail)) from exc
    except urllib.error.URLError as exc:
        raise GmailApiError(0, f"Gmail API connection failed: {exc.reason}") from exc
    if not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GmailApiError(0, "Gmail API returned non-JSON.") from exc
    if not isinstance(payload, dict):
        raise GmailApiError(0, "Gmail API returned an invalid payload.")
    return payload


def _error_message(status: int, detail: str) -> str:
    parsed_message = ""
    try:
        payload = json.loads(detail) if detail else {}
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                parsed_message = str(error.get("message") or "").strip()
            elif isinstance(error, str):
                parsed_message = error.strip()
    except json.JSONDecodeError:
        parsed_message = ""
    if status == 401:
        return SIGN_IN_REQUIRED
    if status == 403:
        return (
            parsed_message
            or "Gmail API permission denied. Re-sign in with Google in Tools Ops so Gmail scopes are granted."
        )
    return parsed_message or detail.strip()[:240] or f"Gmail API request failed ({status})."


class GmailApiError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class GmailClient:
    def __init__(self, token: str, *, request_fn: Optional[HttpRequestFn] = None):
        self.token = str(token or "").strip()
        self._request_fn = request_fn or _default_http_request

    def require_token(self) -> None:
        if not self.token:
            raise GmailApiError(401, SIGN_IN_REQUIRED)

    def request(self, method: str, path: str, *, query: Optional[Dict[str, Any]] = None, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        self.require_token()
        url = f"{GMAIL_API_ROOT}{path}"
        if query:
            encoded = urllib.parse.urlencode(
                {key: value for key, value in query.items() if value is not None},
                doseq=True,
            )
            if encoded:
                url = f"{url}?{encoded}"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
        }
        encoded_body = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            encoded_body = json.dumps(body).encode("utf-8")
        return self._request_fn(method, url, headers, encoded_body)

    def create_draft(self, to: Recipient, subject: str, body: str) -> str:
        recipients = normalize_recipients(to)
        if not recipients:
            raise GmailApiError(400, "A draft requires at least one recipient.")
        payload = self.request(
            "POST",
            "/drafts",
            body={"message": {"raw": encode_raw_message(recipients, subject, body)}},
        )
        draft_id = str(payload.get("id") or "").strip()
        message = payload.get("message") if isinstance(payload.get("message"), dict) else {}
        message_id = str(message.get("id") or "").strip()
        to_text = ", ".join(recipients)
        if draft_id:
            return f"Created Gmail draft {draft_id} to {to_text}." + (f" Message id {message_id}." if message_id else "")
        return f"Created a Gmail draft to {to_text}."

    def send_message(self, to: Recipient, subject: str, body: str) -> str:
        recipients = normalize_recipients(to)
        if not recipients:
            raise GmailApiError(400, "A send requires at least one recipient.")
        payload = self.request(
            "POST",
            "/messages/send",
            body={"raw": encode_raw_message(recipients, subject, body)},
        )
        message_id = str(payload.get("id") or "").strip()
        to_text = ", ".join(recipients)
        if message_id:
            return f"Sent Gmail message {message_id} to {to_text}."
        return f"Sent a Gmail message to {to_text}."

    def list_messages(self, limit: int = 5) -> str:
        return self._format_message_lines(self.list_message_items(max_results=limit, label_ids=["INBOX"]))

    def search_messages(self, query: str) -> str:
        return self._format_message_lines(self.list_message_items(max_results=5, query=query))

    def list_message_items(
        self,
        *,
        max_results: int = 5,
        query: Optional[str] = None,
        label_ids: Optional[Sequence[str]] = None,
    ) -> List[Dict[str, str]]:
        capped = max(1, min(int(max_results or 5), 20))
        params: Dict[str, Any] = {"maxResults": capped}
        if query:
            params["q"] = query
        elif label_ids:
            params["labelIds"] = [str(item) for item in label_ids if str(item).strip()]
        listing = self.request("GET", "/messages", query=params)
        messages = listing.get("messages") if isinstance(listing.get("messages"), list) else []
        rows: List[Dict[str, str]] = []
        for item in messages[:capped]:
            if not isinstance(item, dict):
                continue
            message_id = str(item.get("id") or "").strip()
            if not message_id:
                continue
            detail = self.request(
                "GET",
                f"/messages/{urllib.parse.quote(message_id)}",
                query={"format": "metadata", "metadataHeaders": ["From", "Subject", "Date"]},
            )
            payload = detail.get("payload") if isinstance(detail.get("payload"), dict) else {}
            headers = {
                str(header.get("name") or "").lower(): str(header.get("value") or "")
                for header in payload.get("headers") or []
                if isinstance(header, dict)
            }
            rows.append({
                "id": message_id,
                "from": headers.get("from") or "unknown",
                "subject": headers.get("subject") or "(no subject)",
                "date": headers.get("date") or "",
                "snippet": str(detail.get("snippet") or "").strip(),
            })
        return rows

    def _format_message_lines(self, rows: List[Dict[str, str]]) -> str:
        if not rows:
            return "No Gmail messages matched."
        lines: List[str] = []
        for row in rows:
            snippet = row.get("snippet") or ""
            lines.append(
                f"- {row.get('date') or row.get('id')} | {row.get('from') or 'unknown'} | "
                f"{row.get('subject') or '(no subject)'}"
                + (f" — {snippet}" if snippet else "")
            )
        return "\n".join(lines)
