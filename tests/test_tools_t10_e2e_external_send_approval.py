import json

import pytest

from src.db import init_db
from src.hitl.approval_engine import create_approval_request, get_approval_request
from src.harness.graph import resume_graph_after_approval
from src.tools.mcp_invocation import MCPInvocationStatus, invoke_provider_tool
from src.tools.mcp_provider_registry import clear_mcp_provider_discovery_cache
from src.tools.policy import ToolCallerSource


class FakeGmailClient:
    def __init__(self):
        self.calls = []

    def list_tools(self):
        return [
            {
                "name": "gmail_send",
                "description": "Send Gmail",
                "inputSchema": {"type": "object", "required": ["to"], "properties": {"to": {"type": "string"}}},
            }
        ]

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return {"ok": True}

    def close(self):
        pass


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "tools_t10_external_send.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    monkeypatch.setattr("src.mcp_gateway.registry.load_live_mcp_tools", lambda: [])
    clear_mcp_provider_discovery_cache()
    init_db(db_file)
    return db_file


def _config(path):
    config = path / "mcp_config.json"
    config.write_text(json.dumps({"mcpServers": {"gmail": {"transport": "stdio", "command": "fake-gmail"}}}), encoding="utf-8")
    return config


def test_t10_external_gmail_send_requires_approval_before_tools_call(tmp_path):
    clear_mcp_provider_discovery_cache()
    client = FakeGmailClient()

    result = invoke_provider_tool(
        provider_ids=("gmail",),
        tool_hints=("send",),
        arguments={"to": "user@example.com", "subject": "Hi", "body": "Hello"},
        config_path=_config(tmp_path),
        client_factory=lambda _provider: client,
        source=ToolCallerSource.CHAT,
    )

    assert result.status == MCPInvocationStatus.APPROVAL_REQUIRED
    assert client.calls == []


def test_t10_approved_send_revalidates_policy_and_provider_state(tmp_path):
    clear_mcp_provider_discovery_cache()
    client = FakeGmailClient()

    result = invoke_provider_tool(
        provider_ids=("gmail",),
        tool_hints=("send",),
        arguments={"to": "user@example.com", "subject": "Hi", "body": "Hello"},
        config_path=_config(tmp_path),
        client_factory=lambda _provider: client,
        source=ToolCallerSource.APPROVAL_RESUME,
        approval_context={"approved": True},
    )

    assert result.status == MCPInvocationStatus.SUCCEEDED
    assert client.calls == [("gmail_send", {"to": "user@example.com", "subject": "Hi", "body": "Hello"})]


def test_t10_unavailable_provider_after_approval_fails_closed(temp_db):
    request = create_approval_request(
        "sess",
        "email_send",
        {"to": "user@example.com", "subject": "Hi", "body": "Hello"},
        "send email",
        db_path=temp_db,
    )

    result = resume_graph_after_approval(request["request_id"], "APPROVED")

    assert result["status"] == "UNAVAILABLE"
    assert "unavailable" in result["message"].lower()
    assert get_approval_request(request["request_id"], db_path=temp_db)["status"] == "REJECTED"
