import json

from src.tools.mcp_invocation import MCPInvocationStatus, invoke_provider_tool
from src.tools.mcp_provider_registry import clear_mcp_provider_discovery_cache
from src.tools.policy import ToolCallerSource


class FakeMCPClient:
    def __init__(self, tools):
        self.tools = tools
        self.calls = []

    def list_tools(self):
        return self.tools

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return json.dumps({"ok": True, "tool": name}, sort_keys=True)

    def close(self):
        pass


def _config(tmp_path):
    config = tmp_path / "mcp_config.json"
    config.write_text(json.dumps({"mcpServers": {"gmail": {"transport": "stdio", "command": "fake-gmail"}}}), encoding="utf-8")
    return config


def test_t8_mcp_call_not_reached_when_policy_requires_approval(tmp_path):
    clear_mcp_provider_discovery_cache()
    client = FakeMCPClient([{"name": "gmail_send", "inputSchema": {"type": "object", "required": ["to"]}}])
    result = invoke_provider_tool(
        provider_ids=("gmail",),
        tool_hints=("send",),
        arguments={"to": "a@example.com"},
        config_path=_config(tmp_path),
        client_factory=lambda _provider: client,
        source=ToolCallerSource.CHAT,
    )
    assert result.status == MCPInvocationStatus.APPROVAL_REQUIRED
    assert client.calls == []


def test_t8_mcp_call_reached_after_approved_resume(tmp_path):
    clear_mcp_provider_discovery_cache()
    client = FakeMCPClient([{"name": "gmail_send", "inputSchema": {"type": "object", "required": ["to"]}}])
    result = invoke_provider_tool(
        provider_ids=("gmail",),
        tool_hints=("send",),
        arguments={"to": "a@example.com"},
        config_path=_config(tmp_path),
        client_factory=lambda _provider: client,
        source=ToolCallerSource.APPROVAL_RESUME,
        approval_context={"approved": True},
    )
    assert result.status == MCPInvocationStatus.SUCCEEDED
    assert client.calls == [("gmail_send", {"to": "a@example.com"})]


def test_t8_mcp_read_call_reaches_provider_without_approval(tmp_path):
    clear_mcp_provider_discovery_cache()
    client = FakeMCPClient([{"name": "gmail_search", "inputSchema": {"type": "object", "required": ["query"]}}])
    result = invoke_provider_tool(
        provider_ids=("gmail",),
        tool_hints=("search",),
        arguments={"query": "from:alice"},
        config_path=_config(tmp_path),
        client_factory=lambda _provider: client,
        source=ToolCallerSource.CHAT,
    )
    assert result.status == MCPInvocationStatus.SUCCEEDED
    assert client.calls == [("gmail_search", {"query": "from:alice"})]