"""Stdio MCP server that talks to the Gmail API for personal @gmail.com accounts."""

from __future__ import annotations

import json
import sys
from typing import Any, Dict, Optional

from src.mcp_gateway.gmail_api import GmailApiError, GmailClient, access_token_from_env
from src.mcp_gateway.protocol.json_rpc import build_response

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "astra-gmail-local", "version": "1.0.0"}

TOOLS = [
    {
        "name": "create_draft",
        "description": "Create a Gmail draft in the signed-in personal Gmail account.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "to": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Recipient email addresses",
                },
                "subject": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["to", "subject", "body"],
        },
    },
    {
        "name": "send_message",
        "description": "Send an email from the signed-in personal Gmail account.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "to": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Recipient email addresses",
                },
                "subject": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["to", "subject", "body"],
        },
    },
    {
        "name": "gmail_search",
        "description": "Search the signed-in personal Gmail account.",
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "list_messages",
        "description": "List recent Inbox messages from the signed-in personal Gmail account.",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer"}},
        },
    },
]


def _text_result(text: str, *, is_error: bool = False) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def handle_rpc(message: Dict[str, Any], *, client: Optional[GmailClient] = None) -> Optional[Dict[str, Any]]:
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
        return build_response(request_id, result=_call_tool(params, client=client or GmailClient(access_token_from_env())))
    return build_response(
        request_id,
        error={"code": -32601, "message": f"Method not found: {method}"},
    )


def _call_tool(params: Dict[str, Any], *, client: GmailClient) -> Dict[str, Any]:
    name = str(params.get("name") or "").strip()
    arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
    try:
        if name == "create_draft":
            return _text_result(
                client.create_draft(
                    arguments.get("to") or [],
                    str(arguments.get("subject") or ""),
                    str(arguments.get("body") or ""),
                )
            )
        if name == "send_message":
            return _text_result(
                client.send_message(
                    arguments.get("to") or [],
                    str(arguments.get("subject") or ""),
                    str(arguments.get("body") or ""),
                )
            )
        if name == "gmail_search":
            return _text_result(client.search_messages(str(arguments.get("query") or "")))
        if name == "list_messages":
            limit = arguments.get("limit", 5)
            try:
                parsed_limit = int(limit)
            except (TypeError, ValueError):
                parsed_limit = 5
            return _text_result(client.list_messages(parsed_limit))
        return _text_result(f"Unknown Gmail tool: {name}", is_error=True)
    except GmailApiError as exc:
        return _text_result(str(exc), is_error=True)
    except Exception as exc:
        return _text_result(f"Gmail tool failed: {exc}", is_error=True)


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
