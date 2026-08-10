from typing import List, Dict, Any
from langchain_core.tools import BaseTool

from src.mcp_gateway.communication import (
    email_read, email_search, email_draft, email_send,
    whatsapp_read, whatsapp_send,
    telegram_read, telegram_send
)
from src.mcp_gateway.calendar import (
    calendar_inspect_availability, calendar_propose_event, calendar_create_event,
    calendar_update_event, calendar_delete_event
)
from src.mcp_gateway.search import search_web
from src.mcp_gateway.sandboxes.code_sandbox import (
    run_code, github_clone, github_commit_and_push, github_merge
)
from src.mcp_gateway.sandboxes.browser_sandbox import safe_browse_url, capture_screenshot
from src.tools.removed_tools import is_removed_tool_name
from src.tools.registry_types import (
    AvailabilityStatus,
    ImplementationType,
    ToolMetadata,
    approval_policy_for_risk,
    infer_read_write_capability,
    normalize_tool_id_part,
    schema_from_langchain_tool,
)

# Tool Risk Classification Metadata Mapping
TOOL_RISK_MAP: Dict[str, str] = {
    # Low Risk (Read-only / local / safe)
    "email_read": "Low",
    "email_search": "Low",
    "email_draft": "Low",
    "whatsapp_read": "Low",
    "telegram_read": "Low",
    "calendar_inspect_availability": "Low",
    "calendar_propose_event": "Low",
    "calendar_update_event": "Low",
    "calendar_delete_event": "Low",
    "search_web": "Low",
    "run_code": "Low",
    "github_clone": "Low",
    "safe_browse_url": "Low",
    "capture_screenshot": "Low",

    # Medium Risk (Internal updates / scheduling non-critical)
    "github_commit_and_push": "Medium",

    # High Risk (Irreversible side-effects / external messages / payments / merges)
    "email_send": "High",
    "whatsapp_send": "High",
    "telegram_send": "High",
    "calendar_create_event": "High",
    "github_merge": "High",
}

ALL_MCP_TOOLS: List[BaseTool] = [
    # Communication
    email_read, email_search, email_draft, email_send,
    whatsapp_read, whatsapp_send,
    telegram_read, telegram_send,
    # Calendar
    calendar_inspect_availability, calendar_propose_event, calendar_create_event,
    calendar_update_event, calendar_delete_event,
    # Search
    search_web,
    # Code Sandbox & GitHub
    run_code, github_clone, github_commit_and_push, github_merge,
    # Browser Sandbox
    safe_browse_url, capture_screenshot
]



from src.mcp_gateway.mcp_bridge import load_live_mcp_tools

def get_all_mcp_tools() -> List[BaseTool]:
    """
    Returns currently active MCP gateway tools for LangChain/LangGraph binding.

    T2 filters browser/code sandbox tools from active exposure. The sandbox
    modules still exist on disk until T3 cleanup.
    """
    live_tools = load_live_mcp_tools()
    active_static_tools = [tool for tool in ALL_MCP_TOOLS if not is_removed_tool_name(tool.name)]
    active_live_tools = [tool for tool in live_tools if not is_removed_tool_name(tool.name)]
    return active_static_tools + active_live_tools

def get_mcp_tool_risk(tool_name: str) -> str:
    """Returns the risk level for a tool by name, including T2 blocked tools."""
    if is_removed_tool_name(tool_name):
        return "Blocked"
    return TOOL_RISK_MAP.get(tool_name, "Low")

def get_mcp_tool_catalog() -> List[Dict[str, Any]]:
    """Returns catalog metadata for all registered MCP gateway tools."""
    tools = get_all_mcp_tools()
    return [
        {
            "name": t.name,
            "description": t.description,
            "risk_level": get_mcp_tool_risk(t.name)
        }
        for t in tools
    ]

_MCP_GATEWAY_TOOL_CATEGORIES: Dict[str, str] = {
    "email_read": "gmail_legacy_adapter",
    "email_search": "gmail_legacy_adapter",
    "email_draft": "gmail_legacy_adapter",
    "email_send": "gmail_legacy_adapter",
    "whatsapp_read": "whatsapp_legacy_adapter",
    "whatsapp_send": "whatsapp_legacy_adapter",
    "telegram_read": "telegram_legacy_adapter",
    "telegram_send": "telegram_legacy_adapter",
    "calendar_inspect_availability": "google_calendar_legacy_adapter",
    "calendar_propose_event": "google_calendar_legacy_adapter",
    "calendar_create_event": "google_calendar_legacy_adapter",
    "calendar_update_event": "google_calendar_legacy_adapter",
    "calendar_delete_event": "google_calendar_legacy_adapter",
    "search_web": "search_legacy_adapter",
    "run_code": "code_sandbox",
    "github_clone": "code_sandbox",
    "github_commit_and_push": "code_sandbox",
    "github_merge": "code_sandbox",
    "safe_browse_url": "browser_sandbox",
    "capture_screenshot": "browser_sandbox",
}

_EXTERNAL_SIDE_EFFECT_TOOLS = {
    "email_send",
    "whatsapp_send",
    "telegram_send",
    "calendar_create_event",
    "calendar_update_event",
    "calendar_delete_event",
    "search_web",
    "safe_browse_url",
    "capture_screenshot",
    "github_clone",
    "github_commit_and_push",
    "github_merge",
}

_DESTRUCTIVE_TOOLS = {"calendar_delete_event", "github_merge", "run_code"}


def get_mcp_gateway_tool_metadata() -> List[ToolMetadata]:
    """Returns transitional metadata for active MCP gateway/local adapter tools."""
    metadata: List[ToolMetadata] = []
    for tool in ALL_MCP_TOOLS:
        if is_removed_tool_name(tool.name):
            continue
        risk_class = get_mcp_tool_risk(tool.name)
        metadata.append(
            ToolMetadata(
                tool_id=f"mcp.gateway_legacy.{normalize_tool_id_part(tool.name)}",
                legacy_name=tool.name,
                display_name=tool.name.replace("_", " ").title(),
                provider="mcp_gateway",
                category=_MCP_GATEWAY_TOOL_CATEGORIES.get(tool.name, "mcp_gateway_legacy"),
                implementation_type=ImplementationType.MCP,
                enabled=True,
                availability_status=AvailabilityStatus.AVAILABLE,
                risk_class=risk_class,
                approval_policy=approval_policy_for_risk(risk_class),
                read_write_capability=infer_read_write_capability(tool.name),
                external_side_effect=tool.name in _EXTERNAL_SIDE_EFFECT_TOOLS,
                destructive=tool.name in _DESTRUCTIVE_TOOLS,
                scheduled_capable=False,
                provider_managed=False,
                input_schema=schema_from_langchain_tool(tool),
                output_schema_hint="text",
                observability_metadata={
                    "migration_phase": "T2",
                    "active_legacy_tool": True,
                    "legacy_local_adapter_backed": True,
                    "provider_managed_target": True,
                    "registry_source": "src.mcp_gateway.registry",
                },
            )
        )
    return metadata

