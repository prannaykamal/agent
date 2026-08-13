"""Google Calendar REST helpers for the local personal-calendar MCP server."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

CALENDAR_API_ROOT = "https://www.googleapis.com/calendar/v3"
SIGN_IN_REQUIRED = (
    "Google sign-in required. Open Tools Ops and click Sign in with Google for Calendar."
)

HttpRequestFn = Callable[[str, str, Optional[Dict[str, str]], Optional[bytes]], Dict[str, Any]]


def access_token_from_env(env: Optional[Dict[str, str]] = None) -> str:
    source = env if env is not None else os.environ
    return str(
        source.get("CALENDAR_ACCESS_TOKEN")
        or source.get("GOOGLE_ACCESS_TOKEN")
        or source.get("GMAIL_ACCESS_TOKEN")
        or ""
    ).strip()


def _local_now() -> datetime:
    return datetime.now().astimezone()


def parse_datetime(value: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise CalendarApiError(400, "A start or end time is required.")
    if re.fullmatch(r"\d{1,2}:\d{2}(?::\d{2})?", text):
        parts = [int(part) for part in text.split(":")]
        while len(parts) < 3:
            parts.append(0)
        now = _local_now()
        return now.replace(hour=parts[0], minute=parts[1], second=parts[2], microsecond=0)
    normalized = text.replace("Z", "+00:00")
    if " " in normalized and "T" not in normalized:
        normalized = normalized.replace(" ", "T", 1)
    try:
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=_local_now().tzinfo)
        return parsed
    except ValueError:
        pass
    try_values = [text]
    if " " in text and "T" not in text:
        try_values.append(text.replace(" ", "T", 1))
    for candidate in try_values:
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(candidate, fmt)
                return parsed.replace(tzinfo=_local_now().tzinfo)
            except ValueError:
                continue
    raise CalendarApiError(400, f"Could not parse datetime '{text}'. Use ISO format such as 2026-08-15T05:00:00.")


def to_rfc3339(value: str) -> str:
    return parse_datetime(value).isoformat()


def _default_http_request(method: str, url: str, headers: Optional[Dict[str, str]], body: Optional[bytes]) -> Dict[str, Any]:
    request = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise CalendarApiError(exc.code, _error_message(exc.code, detail)) from exc
    except urllib.error.URLError as exc:
        raise CalendarApiError(0, f"Google Calendar API connection failed: {exc.reason}") from exc
    if not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CalendarApiError(0, "Google Calendar API returned non-JSON.") from exc
    if not isinstance(payload, dict):
        raise CalendarApiError(0, "Google Calendar API returned an invalid payload.")
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
            or "Calendar API permission denied. Re-sign in with Google in Tools Ops so Calendar event scopes are granted."
        )
    return parsed_message or detail.strip()[:240] or f"Google Calendar API request failed ({status})."


class CalendarApiError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class CalendarClient:
    def __init__(self, token: str, *, request_fn: Optional[HttpRequestFn] = None):
        self.token = str(token or "").strip()
        self._request_fn = request_fn or _default_http_request

    def require_token(self) -> None:
        if not self.token:
            raise CalendarApiError(401, SIGN_IN_REQUIRED)

    def request(self, method: str, path: str, *, query: Optional[Dict[str, Any]] = None, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        self.require_token()
        url = f"{CALENDAR_API_ROOT}{path}"
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

    def list_event_items(self, start_date: str = "", end_date: str = "", *, max_results: int = 25) -> List[Dict[str, Any]]:
        time_min = to_rfc3339(start_date) if str(start_date or "").strip() else _local_now().isoformat()
        if str(end_date or "").strip():
            time_max = to_rfc3339(end_date)
        else:
            time_max = (_local_now() + timedelta(days=7)).isoformat()
        payload = self.request(
            "GET",
            "/calendars/primary/events",
            query={
                "timeMin": time_min,
                "timeMax": time_max,
                "singleEvents": "true",
                "orderBy": "startTime",
                "maxResults": max(1, min(int(max_results or 25), 50)),
            },
        )
        items = payload.get("items") if isinstance(payload.get("items"), list) else []
        return [item for item in items if isinstance(item, dict)]

    def list_events(self, start_date: str = "", end_date: str = "") -> str:
        items = self.list_event_items(start_date, end_date, max_results=10)
        if not items:
            return "No calendar events in that window."
        lines: List[str] = []
        for item in items:
            summary = str(item.get("summary") or "(no title)").strip()
            event_id = str(item.get("id") or "").strip()
            start = _event_time(item.get("start"))
            end = _event_time(item.get("end"))
            lines.append(f"- {start} – {end} | {summary}" + (f" [{event_id}]" if event_id else ""))
        return "\n".join(lines) if lines else "No calendar events in that window."

    def list_events_structured(self, start_date: str = "", end_date: str = "") -> List[Dict[str, str]]:
        rows: List[Dict[str, str]] = []
        for item in self.list_event_items(start_date, end_date, max_results=25):
            rows.append({
                "id": str(item.get("id") or "").strip(),
                "title": str(item.get("summary") or "(no title)").strip(),
                "start_time": _event_time(item.get("start")),
                "end_time": _event_time(item.get("end")),
                "location": str(item.get("location") or "").strip(),
            })
        return rows

    def find_conflicts(self, start_time: str, end_time: str, exclude_id: str = "") -> List[Dict[str, Any]]:
        start = parse_datetime(start_time)
        end = parse_datetime(end_time) if str(end_time or "").strip() else start + timedelta(hours=1)
        if end <= start:
            end = start + timedelta(hours=1)
        items = self.list_event_items(start.isoformat(), end.isoformat())
        conflicts: List[Dict[str, Any]] = []
        exclude = str(exclude_id or "").strip()
        for item in items:
            event_id = str(item.get("id") or "").strip()
            if exclude and event_id == exclude:
                continue
            other_start = _parse_event_datetime(item.get("start"))
            other_end = _parse_event_datetime(item.get("end"))
            if other_start is None or other_end is None:
                continue
            if other_start < end and other_end > start:
                conflicts.append({
                    "id": event_id,
                    "title": str(item.get("summary") or "(no title)").strip(),
                    "start_time": other_start.isoformat(),
                    "end_time": other_end.isoformat(),
                })
        return conflicts

    def create_event(self, title: str, start_time: str, end_time: str = "", attendees: str = "", location: str = "") -> str:
        start = parse_datetime(start_time)
        end = parse_datetime(end_time) if str(end_time or "").strip() else start + timedelta(hours=1)
        body: Dict[str, Any] = {
            "summary": str(title or "Meeting").strip() or "Meeting",
            "start": {"dateTime": start.isoformat()},
            "end": {"dateTime": end.isoformat()},
        }
        if str(location or "").strip():
            body["location"] = str(location).strip()
        attendee_list = _parse_attendees(attendees)
        if attendee_list:
            body["attendees"] = [{"email": email} for email in attendee_list]
        payload = self.request("POST", "/calendars/primary/events", body=body)
        event_id = str(payload.get("id") or "").strip()
        summary = str(payload.get("summary") or body["summary"]).strip()
        html_link = str(payload.get("htmlLink") or "").strip()
        text = f"Created calendar event '{summary}' from {start.isoformat()} to {end.isoformat()}."
        if event_id:
            text += f" Event id {event_id}."
        if html_link:
            text += f" {html_link}"
        return text

    def update_event(self, event_id: str, title: str = "", start_time: str = "", end_time: str = "", attendees: str = "", location: str = "", status: str = "") -> str:
        clean_id = str(event_id or "").strip()
        if not clean_id:
            raise CalendarApiError(400, "An event_id is required to update a calendar event.")
        body: Dict[str, Any] = {}
        if str(title or "").strip():
            body["summary"] = str(title).strip()
        if str(start_time or "").strip():
            body["start"] = {"dateTime": to_rfc3339(start_time)}
        if str(end_time or "").strip():
            body["end"] = {"dateTime": to_rfc3339(end_time)}
        if str(location or "").strip():
            body["location"] = str(location).strip()
        if str(status or "").strip():
            body["status"] = str(status).strip().lower()
        attendee_list = _parse_attendees(attendees)
        if attendee_list:
            body["attendees"] = [{"email": email} for email in attendee_list]
        if not body:
            raise CalendarApiError(400, "No calendar fields were provided to update.")
        payload = self.request(
            "PATCH",
            f"/calendars/primary/events/{urllib.parse.quote(clean_id)}",
            body=body,
        )
        summary = str(payload.get("summary") or title or clean_id).strip()
        return f"Updated calendar event '{summary}' ({clean_id})."

    def delete_event(self, event_id: str) -> str:
        clean_id = str(event_id or "").strip()
        if not clean_id:
            raise CalendarApiError(400, "An event_id is required to delete a calendar event.")
        self.request("DELETE", f"/calendars/primary/events/{urllib.parse.quote(clean_id)}")
        return f"Deleted calendar event {clean_id}."


def _parse_attendees(attendees: str) -> List[str]:
    return [part.strip() for part in str(attendees or "").replace(";", ",").split(",") if part.strip() and "@" in part]


def _event_time(value: Any) -> str:
    if not isinstance(value, dict):
        return "unknown"
    return str(value.get("dateTime") or value.get("date") or "unknown")


def _parse_event_datetime(value: Any) -> Optional[datetime]:
    text = _event_time(value)
    if text == "unknown":
        return None
    try:
        return parse_datetime(text)
    except CalendarApiError:
        return None
