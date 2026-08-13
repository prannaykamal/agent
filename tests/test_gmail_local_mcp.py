import json
from email import message_from_bytes
import base64

from src.config import BASE_DIR
from src.mcp_gateway.gmail_api import (
    GMAIL_API_ROOT,
    SIGN_IN_REQUIRED,
    GmailApiError,
    GmailClient,
    encode_raw_message,
)
from src.mcp_gateway.gmail_local_mcp import TOOLS, handle_rpc
from src.mcp_gateway.protocol.client import MCPClient
from src.mcp_gateway.protocol.oauth import stdio_env_with_oauth
from src.mcp_gateway.protocol.transports.stdio import StdioMCPTransport


def test_encode_raw_message_includes_recipients_and_subject():
    raw = encode_raw_message(["a@example.com", "b@example.com"], "Hello", "Body text")
    padding = "=" * (-len(raw) % 4)
    parsed = message_from_bytes(base64.urlsafe_b64decode(raw + padding))
    assert parsed["To"] == "a@example.com, b@example.com"
    assert parsed["Subject"] == "Hello"
    assert parsed.get_payload(decode=True).decode("utf-8") == "Body text"


def test_gmail_create_draft_posts_raw_message():
    captured = {}

    def fake_request(method, url, headers, body):
        captured["method"] = method
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = json.loads(body.decode("utf-8"))
        return {"id": "draft-1", "message": {"id": "msg-1"}}

    client = GmailClient("ya29-test", request_fn=fake_request)
    text = client.create_draft(["user@example.com"], "Hi", "Hello")
    assert captured["method"] == "POST"
    assert captured["url"] == f"{GMAIL_API_ROOT}/drafts"
    assert captured["headers"]["Authorization"] == "Bearer ya29-test"
    assert "raw" in captured["body"]["message"]
    assert "Created Gmail draft draft-1 to user@example.com." in text


def test_gmail_send_message_posts_raw_message():
    captured = {}

    def fake_request(method, url, headers, body):
        captured["method"] = method
        captured["url"] = url
        captured["body"] = json.loads(body.decode("utf-8"))
        return {"id": "msg-sent-1", "labelIds": ["SENT"]}

    client = GmailClient("ya29-test", request_fn=fake_request)
    text = client.send_message(["user@example.com"], "Hi", "Hello")
    assert captured["method"] == "POST"
    assert captured["url"] == f"{GMAIL_API_ROOT}/messages/send"
    assert "raw" in captured["body"]
    assert "Sent Gmail message msg-sent-1 to user@example.com." in text


def test_gmail_list_and_search_summarize_headers():
    def fake_request(method, url, headers, body):
        if url.startswith(f"{GMAIL_API_ROOT}/messages?") and "q=" in url:
            return {"messages": [{"id": "abc"}]}
        if url.startswith(f"{GMAIL_API_ROOT}/messages?") :
            return {"messages": [{"id": "abc"}]}
        if url.startswith(f"{GMAIL_API_ROOT}/messages/abc"):
            return {
                "snippet": "hello there",
                "payload": {
                    "headers": [
                        {"name": "From", "value": "Ada <ada@example.com>"},
                        {"name": "Subject", "value": "Invoice"},
                        {"name": "Date", "value": "Thu, 13 Aug 2026"},
                    ]
                },
            }
        raise AssertionError(url)

    client = GmailClient("token", request_fn=fake_request)
    listed = client.list_messages(1)
    assert "Ada <ada@example.com>" in listed
    assert "Invoice" in listed
    searched = client.search_messages("from:ada")
    assert "hello there" in searched


def test_gmail_list_messages_filters_inbox():
    captured = {}

    def fake_request(method, url, headers, body):
        captured["url"] = url
        if url.startswith(f"{GMAIL_API_ROOT}/messages?"):
            assert "labelIds=INBOX" in url
            return {"messages": []}
        raise AssertionError(url)

    client = GmailClient("token", request_fn=fake_request)
    assert client.list_messages(3) == "No Gmail messages matched."
    assert "q=" not in captured["url"]


def test_gmail_missing_token_asks_for_sign_in():
    client = GmailClient("")
    try:
        client.list_messages()
        raise AssertionError("expected GmailApiError")
    except GmailApiError as exc:
        assert exc.status == 401
        assert str(exc) == SIGN_IN_REQUIRED


def test_local_mcp_lists_personal_gmail_tools():
    response = handle_rpc({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    names = [item["name"] for item in response["result"]["tools"]]
    assert names == ["create_draft", "send_message", "gmail_search", "list_messages"]
    assert {item["name"] for item in TOOLS} == set(names)


def test_local_mcp_create_draft_uses_gmail_client():
    class FakeClient:
        def create_draft(self, to, subject, body):
            return f"Created Gmail draft x to {to[0]} ({subject}: {body})."

    response = handle_rpc(
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {
                "name": "create_draft",
                "arguments": {"to": ["a@example.com"], "subject": "Hi", "body": "Hello"},
            },
        },
        client=FakeClient(),
    )
    assert response["result"]["isError"] is False
    assert "a@example.com" in response["result"]["content"][0]["text"]


def test_local_mcp_send_message_uses_gmail_client():
    class FakeClient:
        def send_message(self, to, subject, body):
            return f"Sent Gmail message x to {to[0]}."

    response = handle_rpc(
        {
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {
                "name": "send_message",
                "arguments": {"to": ["a@example.com"], "subject": "Hi", "body": "Hello"},
            },
        },
        client=FakeClient(),
    )
    assert response["result"]["isError"] is False
    assert "Sent Gmail message" in response["result"]["content"][0]["text"]


def test_local_mcp_reports_sign_in_error():
    class FakeClient:
        def create_draft(self, to, subject, body):
            raise GmailApiError(401, SIGN_IN_REQUIRED)

    response = handle_rpc(
        {
            "jsonrpc": "2.0",
            "id": 8,
            "method": "tools/call",
            "params": {"name": "create_draft", "arguments": {"to": ["a@example.com"], "subject": "Hi", "body": "Hello"}},
        },
        client=FakeClient(),
    )
    assert response["result"]["isError"] is True
    assert SIGN_IN_REQUIRED in response["result"]["content"][0]["text"]


def test_stdio_env_injects_gmail_access_token(tmp_path):
    env = stdio_env_with_oauth(
        {"EXISTING": "1"},
        {"accessToken": "ya29-injected"},
        project_root=tmp_path,
    )
    assert env["EXISTING"] == "1"
    assert env["GMAIL_ACCESS_TOKEN"] == "ya29-injected"
    assert env["GOOGLE_ACCESS_TOKEN"] == "ya29-injected"
    assert env["PYTHONUNBUFFERED"] == "1"
    assert str(tmp_path) in env["PYTHONPATH"]


def test_call_tool_raises_when_mcp_sets_is_error():
    class FakeTransport:
        def connect(self):
            return None

        def send_request(self, request_dict):
            method = request_dict.get("method")
            if method == "initialize":
                return {"result": {"serverInfo": {"name": "fake"}, "capabilities": {}}}
            if method == "tools/call":
                return {
                    "result": {
                        "isError": True,
                        "content": [{"type": "text", "text": SIGN_IN_REQUIRED}],
                    }
                }
            return {}

        def close(self):
            return None

    client = MCPClient(FakeTransport())
    try:
        client.call_tool("create_draft", {"to": ["a@example.com"]})
        raise AssertionError("expected RuntimeError")
    except RuntimeError as exc:
        assert SIGN_IN_REQUIRED in str(exc)


def test_local_gmail_mcp_stdio_roundtrip_without_token():
    import os
    import sys

    env = dict(os.environ)
    env.pop("GMAIL_ACCESS_TOKEN", None)
    env.pop("GOOGLE_ACCESS_TOKEN", None)
    env["PYTHONPATH"] = str(BASE_DIR)
    env["PYTHONUNBUFFERED"] = "1"
    transport = StdioMCPTransport(
        command=sys.executable,
        args=["-m", "src.mcp_gateway.gmail_local_mcp"],
        env=env,
        cwd=str(BASE_DIR),
    )
    client = MCPClient(transport)
    try:
        client.connect_and_initialize()
        names = [item["name"] for item in client.list_tools()]
        assert "create_draft" in names
        try:
            client.call_tool("create_draft", {"to": ["a@example.com"], "subject": "Hi", "body": "Hello"})
            raise AssertionError("expected sign-in error")
        except RuntimeError as exc:
            assert SIGN_IN_REQUIRED in str(exc)
    finally:
        client.close()
