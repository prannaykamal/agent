from dataclasses import replace

from src.tools.mcp_provider_config import MCPDiscoveryStatus, TARGET_MCP_PROVIDER_DEFAULTS
from src.tools.mcp_schema import classify_mcp_tool, normalize_mcp_input_schema, normalize_mcp_tool_metadata
from src.tools.registry_types import ApprovalPolicy, ReadWriteCapability, RiskClass


def test_t6_normalize_mcp_input_schema_defaults_to_object():
    assert normalize_mcp_input_schema(None) == {"type": "object", "properties": {}}
    assert normalize_mcp_input_schema({"properties": []})["properties"] == {}


def test_t6_search_tools_are_read_only_external_without_approval():
    risk, approval, capability, external, destructive, scheduled = classify_mcp_tool("search_tavily", "tavily_search")

    assert risk == RiskClass.LOW
    assert approval == ApprovalPolicy.NO_APPROVAL_NEEDED
    assert capability == ReadWriteCapability.READ_ONLY
    assert external is True
    assert destructive is False
    assert scheduled is False


def test_t6_provider_policy_overlays_are_conservative_for_mcp_writes():
    assert classify_mcp_tool("google_calendar", "calendar_create_event")[1] == ApprovalPolicy.APPROVAL_REQUIRED
    assert classify_mcp_tool("gmail", "gmail_send")[1] == ApprovalPolicy.APPROVAL_REQUIRED
    assert classify_mcp_tool("gmail", "gmail_draft")[1] == ApprovalPolicy.CONFIRMATION_RECOMMENDED


def test_t6_normalized_tool_metadata_is_provider_managed_and_stable():
    provider = replace(TARGET_MCP_PROVIDER_DEFAULTS["google_calendar"], enabled=True).with_discovery(
        discovery_status=MCPDiscoveryStatus.DISCOVERED
    )
    metadata = normalize_mcp_tool_metadata(
        provider,
        {
            "name": "calendar_list_events",
            "description": "List events",
            "inputSchema": {"type": "object", "properties": {"calendar_id": {"type": "string"}}},
        },
    )

    assert metadata.tool_id == "mcp.google_calendar.calendar_list_events"
    assert metadata.legacy_name == "google_calendar_calendar_list_events"
    assert metadata.provider == "google_calendar"
    assert metadata.provider_managed is True
    assert metadata.enabled is True
    assert metadata.input_schema["properties"]["calendar_id"]["type"] == "string"
