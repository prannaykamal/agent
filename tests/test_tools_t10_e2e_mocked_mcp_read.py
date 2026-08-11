import json

from src.tools.mcp_invocation import MCPInvocationStatus, invoke_provider_tool
from src.tools.mcp_provider_registry import clear_mcp_provider_discovery_cache, get_mcp_provider_results
from src.tools.policy import ToolCallerSource


class FakeMCPClient:
    def __init__(self, tools):
        self.tools = tools
        self.calls = []
        self.closed = False

    def list_tools(self):
        return self.tools

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return {"results": [{"title": "Mocked result", "url": "https://example.test", "snippet": arguments["query"]}]}

    def close(self):
        self.closed = True


def test_t10_mocked_search_read_discovers_and_invokes_mcp_tools_call(tmp_path):
    clear_mcp_provider_discovery_cache()
    config_file = tmp_path / "mcp_config.json"
    config_file.write_text(
        json.dumps({"mcpServers": {"search_tavily": {"transport": "stdio", "command": "fake-search"}}}),
        encoding="utf-8",
    )
    client = FakeMCPClient(
        [
            {
                "name": "tavily_search",
                "description": "Search web",
                "inputSchema": {"type": "object", "required": ["query"], "properties": {"query": {"type": "string"}}},
            }
        ]
    )

    results = get_mcp_provider_results(config_path=config_file, refresh=True, client_factory=lambda _provider: client)
    discovered = {result.provider.provider_id: result for result in results}
    assert discovered["search_tavily"].provider.availability_status == "available"
    assert discovered["search_tavily"].tools[0].provider_managed is True

    result = invoke_provider_tool(
        provider_ids=("search_tavily",),
        tool_hints=("search",),
        arguments={"query": "memory architecture"},
        config_path=config_file,
        client_factory=lambda _provider: client,
        source=ToolCallerSource.CHAT,
    )

    assert result.status == MCPInvocationStatus.SUCCEEDED
    assert client.calls == [("tavily_search", {"query": "memory architecture"})]
    assert result.audit_metadata["invocation_boundary"] == "mcp_tools_call"


def test_t10_mocked_read_path_has_no_direct_provider_library_references():
    text = "\n".join(
        [
            open("src/tools/mcp_invocation.py", encoding="utf-8").read(),
            open("src/tools/mcp_provider_registry.py", encoding="utf-8").read(),
            open("src/tools/mcp_schema.py", encoding="utf-8").read(),
        ]
    )
    forbidden = ["TAVILY_API_KEY", "duckduckgo_search", "DDGS", "requests.get", "requests.post", "smtplib", "imaplib"]
    assert not any(item in text for item in forbidden)
