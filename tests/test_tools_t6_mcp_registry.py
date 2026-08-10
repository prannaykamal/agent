import json

import pytest

from src.tools.mcp_provider_registry import (
    clear_mcp_provider_discovery_cache,
    get_mcp_provider_statuses,
    get_provider_managed_mcp_tool_metadata,
)
from src.tools.registry_types import ApprovalPolicy, ImplementationType, RiskClass


class FakeMCPClient:
    def __init__(self, tools):
        self._tools = tools

    def list_tools(self):
        return self._tools

    def close(self):
        pass


@pytest.fixture(autouse=True)
def clear_cache():
    clear_mcp_provider_discovery_cache()
    yield
    clear_mcp_provider_discovery_cache()


def test_t6_discovered_provider_tools_enter_metadata_registry(tmp_path):
    config_file = tmp_path / "mcp_config.json"
    config_file.write_text(
        json.dumps({"mcpServers": {"tavily": {"transport": "stdio", "command": "fake-tavily"}}}),
        encoding="utf-8",
    )

    metadata = get_provider_managed_mcp_tool_metadata(
        config_path=config_file,
        refresh=True,
        client_factory=lambda _provider: FakeMCPClient(
            [{"name": "tavily_search", "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}}}]
        ),
    )

    assert len(metadata) == 1
    tool = metadata[0]
    assert tool.implementation_type == ImplementationType.MCP
    assert tool.provider == "search_tavily"
    assert tool.provider_managed is True
    assert tool.risk_class == RiskClass.LOW
    assert tool.approval_policy == ApprovalPolicy.NO_APPROVAL_NEEDED


def test_t6_unavailable_providers_do_not_produce_bindable_provider_tools(tmp_path):
    metadata = get_provider_managed_mcp_tool_metadata(config_path=tmp_path / "missing.json", refresh=True)

    assert metadata == []


def test_t6_provider_statuses_include_tool_counts_after_discovery(tmp_path):
    config_file = tmp_path / "mcp_config.json"
    config_file.write_text(
        json.dumps({"mcpServers": {"gmail": {"transport": "stdio", "command": "fake-gmail"}}}),
        encoding="utf-8",
    )

    statuses = get_mcp_provider_statuses(
        config_path=config_file,
        refresh=True,
        client_factory=lambda _provider: FakeMCPClient([{"name": "gmail_send", "inputSchema": {"type": "object"}}]),
    )
    by_id = {status["provider_id"]: status for status in statuses}

    assert by_id["gmail"]["availability_status"] == "available"
    assert by_id["gmail"]["tool_count"] == 1
    assert by_id["search_tavily"]["availability_status"] == "unavailable"


def test_t6_removed_sandbox_tools_remain_absent_from_provider_managed_metadata(tmp_path):
    config_file = tmp_path / "mcp_config.json"
    config_file.write_text(
        json.dumps({"mcpServers": {"duckduckgo": {"transport": "stdio", "command": "fake-search"}}}),
        encoding="utf-8",
    )

    metadata = get_provider_managed_mcp_tool_metadata(
        config_path=config_file,
        refresh=True,
        client_factory=lambda _provider: FakeMCPClient(
            [{"name": "duckduckgo.query", "inputSchema": {"type": "object"}}]
        ),
    )
    names = {item.legacy_name for item in metadata}

    assert "safe_browse_url" not in names
    assert "run_code" not in names
