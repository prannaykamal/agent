import json

from src.tools.mcp_provider_config import MCPDiscoveryStatus
from src.tools.mcp_provider_registry import clear_mcp_provider_discovery_cache, get_mcp_provider_statuses


class FakeMCPClient:
    def __init__(self, exc):
        self.exc = exc

    def list_tools(self):
        raise self.exc

    def close(self):
        pass


def test_t6_missing_provider_config_is_safe_unavailable_state(tmp_path):
    clear_mcp_provider_discovery_cache()
    statuses = get_mcp_provider_statuses(config_path=tmp_path / "missing.json", refresh=False)

    assert len(statuses) == 6
    assert all(status["availability_status"] == "unavailable" for status in statuses)
    assert all(status["discovery_status"] == MCPDiscoveryStatus.NOT_CONFIGURED.value for status in statuses)
    assert all(status["tool_count"] == 0 for status in statuses)


def test_t6_discovery_failure_is_redacted_and_non_fatal(tmp_path):
    clear_mcp_provider_discovery_cache()
    config_file = tmp_path / "mcp_config.json"
    config_file.write_text(
        json.dumps({"mcpServers": {"whatsapp": {"transport": "stdio", "command": "fake-whatsapp"}}}),
        encoding="utf-8",
    )

    statuses = get_mcp_provider_statuses(
        config_path=config_file,
        refresh=True,
        client_factory=lambda _provider: FakeMCPClient(RuntimeError("authorization token should not leak")),
    )
    whatsapp = {status["provider_id"]: status for status in statuses}["whatsapp"]

    assert whatsapp["availability_status"] == "unavailable"
    assert whatsapp["discovery_status"] == MCPDiscoveryStatus.FAILED.value
    assert whatsapp["last_error"] == "[REDACTED]"
    assert "should not leak" not in str(whatsapp)


def test_t6_unsupported_transport_is_unavailable_without_startup_failure(tmp_path):
    clear_mcp_provider_discovery_cache()
    config_file = tmp_path / "mcp_config.json"
    config_file.write_text(
        json.dumps({"mcpServers": {"google_calendar": {"transport": "app_connector", "provider_managed": True}}}),
        encoding="utf-8",
    )

    statuses = get_mcp_provider_statuses(config_path=config_file, refresh=True)
    google_calendar = {status["provider_id"]: status for status in statuses}["google_calendar"]

    assert google_calendar["availability_status"] == "unavailable"
    assert google_calendar["discovery_status"] == MCPDiscoveryStatus.UNSUPPORTED_TRANSPORT.value
