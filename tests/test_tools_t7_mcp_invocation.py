import json

from src.tools.mcp_invocation import MCPInvocationStatus, invoke_provider_tool
from src.tools.mcp_provider_registry import clear_mcp_provider_discovery_cache


class FakeMCPClient:
    def __init__(self, tools):
        self.tools = tools
        self.calls = []

    def list_tools(self):
        return self.tools

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return json.dumps({"ok": True, "tool": name, "arguments": arguments}, sort_keys=True)

    def close(self):
        pass


def test_t7_invocation_boundary_uses_mcp_tools_call(tmp_path):
    clear_mcp_provider_discovery_cache()
    config = tmp_path / "mcp_config.json"
    config.write_text(
        json.dumps({"mcpServers": {"gmail": {"transport": "stdio", "command": "fake-gmail"}}}),
        encoding="utf-8",
    )
    client = FakeMCPClient(
        [{"name": "gmail_send", "inputSchema": {"type": "object", "required": ["to"], "properties": {"to": {"type": "string"}}}}]
    )

    result = invoke_provider_tool(
        provider_ids=("gmail",),
        tool_hints=("send",),
        arguments={"to": "user@example.com"},
        config_path=config,
        client_factory=lambda _provider: client,
    )

    assert result.status == MCPInvocationStatus.SUCCEEDED
    assert client.calls == [("gmail_send", {"to": "user@example.com"})]
    assert result.audit_metadata["invocation_boundary"] == "mcp_tools_call"


def test_t7_provider_unavailable_is_safe(tmp_path):
    clear_mcp_provider_discovery_cache()

    result = invoke_provider_tool(
        provider_ids=("gmail",),
        tool_hints=("send",),
        arguments={"to": "user@example.com"},
        config_path=tmp_path / "missing.json",
    )

    assert result.status == MCPInvocationStatus.PROVIDER_UNAVAILABLE
    assert "unavailable" in result.to_text("Gmail MCP").lower()


def test_t7_missing_tool_is_safe(tmp_path):
    clear_mcp_provider_discovery_cache()
    config = tmp_path / "mcp_config.json"
    config.write_text(
        json.dumps({"mcpServers": {"gmail": {"transport": "stdio", "command": "fake-gmail"}}}),
        encoding="utf-8",
    )

    result = invoke_provider_tool(
        provider_ids=("gmail",),
        tool_hints=("send",),
        arguments={"to": "user@example.com"},
        config_path=config,
        client_factory=lambda _provider: FakeMCPClient([{"name": "gmail_search", "inputSchema": {"type": "object"}}]),
    )

    assert result.status == MCPInvocationStatus.TOOL_UNAVAILABLE


def test_t7_argument_validation_uses_discovered_schema(tmp_path):
    clear_mcp_provider_discovery_cache()
    config = tmp_path / "mcp_config.json"
    config.write_text(
        json.dumps({"mcpServers": {"gmail": {"transport": "stdio", "command": "fake-gmail"}}}),
        encoding="utf-8",
    )

    result = invoke_provider_tool(
        provider_ids=("gmail",),
        tool_hints=("send",),
        arguments={"subject": "Missing recipient"},
        config_path=config,
        client_factory=lambda _provider: FakeMCPClient(
            [{"name": "gmail_send", "inputSchema": {"type": "object", "required": ["to"]}}]
        ),
    )

    assert result.status == MCPInvocationStatus.VALIDATION_ERROR
    assert "to" in result.error
