"""Stdio MCP server that talks to the Google Calendar API for personal @gmail.com accounts."""

from __future__ import annotations

import json
import sys
from typing import Any, Dict, Optional

from src.mcp_gateway.calendar_api import CalendarApiError, CalendarClient, access_token_from_env
from src.mcp_gateway.protocol.json_rpc import build_response

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "astra-calendar-local", "version": "1.0.0"}

TOOLS = [
    {
        "name": "create_event",
        "description": "Create an event on the signed-in personal Google Calendar.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "start_time": {"type": "string"},
                "end_time": {"type": "string"},
                "attendees": {"type": "string"},
                "location": {"type": "string"},
            },
            "required": ["title", "start_time"],
        },
    },
    {
        "name": "update_event",
        "description": "Update an event on the signed-in personal Google Calendar.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "event_id": {"type": "string"},
                "title": {"type": "string"},
                "start_time": {"type": "string"},
                "end_time": {"type": "string"},
                "attendees": {"type": "string"},
                "location": {"type": "string"},
                "status": {"type": "string"},
            },
            "required": ["event_id"],
        },
    },
    {
        "name": "delete_event",
        "description": "Delete an event from the signed-in personal Google Calendar.",
        "inputSchema": {
            "type": "object",
            "properties": {"event_id": {"type": "string"}},
            "required": ["event_id"],
        },
    },
    {
        "name": "list_events",
        "description": "List events on the signed-in personal Google Calendar in a time window.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "start_date": {"type": "string"},
                "end_date": {"type": "string"},
            },
        },
    },
]


def _text_result(text: str, *, is_error: bool = False) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def handle_rpc(message: Dict[str, Any], *, client: Optional[CalendarClient] = None) -> Optional[Dict[str, Any]]:
    method = str(message.get("method") or "")
    request_id = message.get("id")
    params = message.get("params") if isinstance(message.get("params"), dict) else {}
    if request_id is None:
        return None
    if method == "initialize":
        return build_response(
            request_id,
            result={
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER_INFO,
            },
        )
    if method == "ping":
        return build_response(request_id, result={})
    if method == "tools/list":
        return build_response(request_id, result={"tools": TOOLS})
    if method == "tools/call":
        return build_response(request_id, result=_call_tool(params, client=client or CalendarClient(access_token_from_env())))
    return build_response(
        request_id,
        error={"code": -32601, "message": f"Method not found: {method}"},
    )


def _call_tool(params: Dict[str, Any], *, client: CalendarClient) -> Dict[str, Any]:
    name = str(params.get("name") or "").strip()
    arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
    try:
        if name == "create_event":
            return _text_result(
                client.create_event(
                    str(arguments.get("title") or "Meeting"),
                    str(arguments.get("start_time") or ""),
                    str(arguments.get("end_time") or ""),
                    str(arguments.get("attendees") or ""),
                    str(arguments.get("location") or ""),
                )
            )
        if name == "update_event":
            return _text_result(
                client.update_event(
                    str(arguments.get("event_id") or ""),
                    str(arguments.get("title") or ""),
                    str(arguments.get("start_time") or ""),
                    str(arguments.get("end_time") or ""),
                    str(arguments.get("attendees") or ""),
                    str(arguments.get("location") or ""),
                    str(arguments.get("status") or ""),
                )
            )
        if name == "delete_event":
            return _text_result(client.delete_event(str(arguments.get("event_id") or "")))
        if name == "list_events":
            return _text_result(
                client.list_events(
                    str(arguments.get("start_date") or ""),
                    str(arguments.get("end_date") or ""),
                )
            )
        return _text_result(f"Unknown Calendar tool: {name}", is_error=True)
    except CalendarApiError as exc:
        return _text_result(str(exc), is_error=True)
    except Exception as exc:
        return _text_result(f"Calendar tool failed: {exc}", is_error=True)


def _read_message() -> Optional[Dict[str, Any]]:
    headers: Dict[str, str] = {}
    while True:
        line = sys.stdin.readline()
        if not line:
            return None
        if line in ("\n", "\r\n"):
            break
        stripped = line.strip()
        if stripped.startswith("{") and "content-length" not in headers:
            return json.loads(stripped)
        if ":" in stripped:
            key, value = stripped.split(":", 1)
            headers[key.strip().lower()] = value.strip()
    if "content-length" not in headers:
        return None
    body = sys.stdin.read(int(headers["content-length"]))
    return json.loads(body)


def _write_message(payload: Dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def main() -> None:
    while True:
        try:
            message = _read_message()
        except Exception:
            continue
        if message is None:
            break
        response = handle_rpc(message)
        if response is not None:
            _write_message(response)


if __name__ == "__main__":
    main()
