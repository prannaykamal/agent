import json

from src.tools.mcp_provider_config import MCPDiscoveryStatus
from src.tools.mcp_provider_registry import (
    clear_mcp_provider_discovery_cache,
    discover_mcp_provider,
    get_mcp_provider_results,
)
from src.tools.mcp_provider_config import load_target_mcp_provider_configs


class FakeMCPClient:
    def __init__(self, tools):
        self._tools = tools
        self.closed = False

    def list_tools(self):
        if isinstance(self._tools, Exception):
            raise self._tools
        return self._tools

    def close(self):
        self.closed = True


def _write_config(path, servers):
    path.write_text(json.dumps({"mcpServers": servers}), encoding="utf-8")


def test_t6_configured_provider_discovers_tools_with_mocked_mcp_client(tmp_path):
    clear_mcp_provider_discovery_cache()
    config_file = tmp_path / "mcp_config.json"
    _write_config(config_file, {"gmail": {"transport": "stdio", "command": "fake-gmail"}})
    provider = load_target_mcp_provider_configs(config_file)["gmail"]

    result = discover_mcp_provider(
        provider,
        client_factory=lambda _provider: FakeMCPClient(
            [
                {
                    "name": "gmail_send",
                    "description": "Send Gmail message",
                    "inputSchema": {"type": "object", "properties": {"to": {"type": "string"}}},
                }
            ]
        ),
    )

    assert result.provider.discovery_status == MCPDiscoveryStatus.DISCOVERED
    assert result.provider.availability_status == "available"
    assert len(result.tools) == 1
    assert result.tools[0].provider == "gmail"
    assert result.tools[0].provider_managed is True


def test_t6_discovery_failure_marks_only_that_provider_unavailable(tmp_path):
    clear_mcp_provider_discovery_cache()
    config_file = tmp_path / "mcp_config.json"
    _write_config(
        config_file,
        {
            "gmail": {"transport": "stdio", "command": "fake-gmail"},
            "google_calendar": {"transport": "stdio", "command": "fake-calendar"},
        },
    )

    def factory(provider):
        if provider.provider_id == "gmail":
            return FakeMCPClient(RuntimeError("missing gmail credential token abc"))
        return FakeMCPClient([{"name": "calendar_list_events", "inputSchema": {"type": "object"}}])

    results = {item.provider.provider_id: item for item in get_mcp_provider_results(config_path=config_file, refresh=True, client_factory=factory)}

    assert results["gmail"].provider.discovery_status == MCPDiscoveryStatus.FAILED
    assert results["gmail"].provider.availability_status == "unavailable"
    assert results["gmail"].provider.last_error == "[REDACTED]"
    assert results["google_calendar"].provider.discovery_status == MCPDiscoveryStatus.DISCOVERED
    assert results["google_calendar"].tools


def test_t6_missing_config_does_not_attempt_discovery(tmp_path):
    clear_mcp_provider_discovery_cache()
    called = False

    def factory(_provider):
        nonlocal called
        called = True
        return FakeMCPClient([])

    results = get_mcp_provider_results(config_path=tmp_path / "missing.json", refresh=True, client_factory=factory)

    assert called is False
    assert all(result.provider.discovery_status == MCPDiscoveryStatus.NOT_CONFIGURED for result in results)
    assert all(not result.tools for result in results)
