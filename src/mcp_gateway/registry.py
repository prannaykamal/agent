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
from src.tools.removed_tools import is_removed_tool_name
from src.tools.mcp_provider_registry import get_provider_managed_mcp_tool_metadata
from src.tools.registry_types import (
    AvailabilityStatus,
    ImplementationType,
    ToolMetadata,
    approval_policy_for_risk,
    infer_read_write_capability,
    normalize_tool_id_part,
    schema_from_langchain_tool,
)

# Provider-managed MCP compatibility metadata overlay
_MCP_POLICY_OVERLAY_RISK: Dict[str, str] = {
    # Low Risk (Read-only / local / safe)
    "email_read": "Low",
    "email_search": "Low",
    "email_draft": "Low",
    "whatsapp_read": "Low",
    "telegram_read": "Low",
    "calendar_inspect_availability": "Low",
    "calendar_propose_event": "Low",
    "search_web": "Low",

    # High Risk (Irreversible side-effects / external messages / payments)
    "email_send": "High",
    "whatsapp_send": "High",
    "telegram_send": "High",
    "calendar_create_event": "High",
    "calendar_update_event": "High",
    "calendar_delete_event": "High",
}


_PROVIDER_FOR_TOOL: Dict[str, str] = {
    "email_read": "gmail",
    "email_search": "gmail",
    "email_draft": "gmail",
    "email_send": "gmail",
    "whatsapp_read": "whatsapp_api",
    "whatsapp_send": "whatsapp_api",
    "telegram_read": "telegram_bot_api",
    "telegram_send": "telegram_bot_api",
    "calendar_inspect_availability": "google_calendar",
    "calendar_propose_event": "google_calendar",
    "calendar_create_event": "google_calendar",
    "calendar_update_event": "google_calendar",
    "calendar_delete_event": "google_calendar",
    "search_web": "search",
}


def _mcp_provider_is_bindable(item: Dict[str, Any]) -> bool:
    if item.get("availability_status") == "available":
        return True
    # Enabled configured providers must be bindable before Tools Ops Discover.
    # Invocation refreshes tools/list. Hiding wrappers makes chat invent
    # manual Gmail/Calendar steps instead of calling email_draft.
    return bool(item.get("enabled") and item.get("configured"))


def _available_provider_ids() -> set[str]:
    from src.tools.mcp_provider_registry import get_mcp_provider_statuses

    statuses = get_mcp_provider_statuses(include_config=False)
    available = {item["provider_id"] for item in statuses if _mcp_provider_is_bindable(item)}
    try:
        from src.external_providers.registry import get_external_provider_statuses

        available.update(
            item["provider_id"]
            for item in get_external_provider_statuses()
            if item.get("availability_status") == "configured"
        )
    except Exception:
        pass
    if "search_tavily" in available or "search_duckduckgo" in available:
        available.add("search")
    return available

def _is_tool_provider_available(tool_name: str) -> bool:
    provider_id = _PROVIDER_FOR_TOOL.get(tool_name)
    return bool(provider_id and provider_id in _available_provider_ids())


ALL_MCP_TOOLS: List[BaseTool] = [
    # Gmail MCP compatibility wrappers
    email_read, email_search, email_draft, email_send,
    # Google Calendar MCP compatibility wrappers
    calendar_inspect_availability, calendar_propose_event, calendar_create_event,
    calendar_update_event, calendar_delete_event,
    # Search MCP compatibility wrapper
    search_web,
]

ALL_EXTERNAL_API_TOOLS: List[BaseTool] = [
    whatsapp_read, whatsapp_send,
    telegram_read, telegram_send,
]



def get_all_mcp_tools() -> List[BaseTool]:
    """
    Returns currently active MCP gateway tools for LangChain/LangGraph binding.

    Chat binds compatibility wrappers only. Raw provider MCP tools are invoked
    through those wrappers so unified policy still recognizes the tool name.
    """
    return [
        tool
        for tool in ALL_MCP_TOOLS
        if not is_removed_tool_name(tool.name) and _is_tool_provider_available(tool.name)
    ]

def get_all_external_api_tools() -> List[BaseTool]:
    """Returns active direct external API provider tools for graph binding."""
    return [
        tool
        for tool in ALL_EXTERNAL_API_TOOLS
        if not is_removed_tool_name(tool.name) and _is_tool_provider_available(tool.name)
    ]


def get_mcp_tool_risk(tool_name: str) -> str:
    """Returns the risk level for a tool by name, including T2 blocked tools."""
    if is_removed_tool_name(tool_name):
        return "Blocked"
    return _MCP_POLICY_OVERLAY_RISK.get(tool_name, "Low")

def get_mcp_tool_catalog() -> List[Dict[str, Any]]:
    """Returns catalog metadata for active MCP-backed tools only."""
    tools = get_all_mcp_tools()
    return [
        {
            "name": t.name,
            "description": t.description,
            "risk_level": get_mcp_tool_risk(t.name)
        }
        for t in tools
    ]


def get_external_api_tool_catalog() -> List[Dict[str, Any]]:
    """Returns catalog metadata for active direct external API provider tools."""
    tools = get_all_external_api_tools()
    return [
        {
            "name": t.name,
            "description": t.description,
            "risk_level": get_mcp_tool_risk(t.name),
            "provider": _PROVIDER_FOR_TOOL.get(t.name),
            "implementation_type": "external_api",
        }
        for t in tools
    ]

_MCP_GATEWAY_TOOL_CATEGORIES: Dict[str, str] = {
    "email_read": "gmail_legacy_adapter",
    "email_search": "gmail_legacy_adapter",
    "email_draft": "gmail_legacy_adapter",
    "email_send": "gmail_legacy_adapter",
    "whatsapp_read": "whatsapp_api_direct",
    "whatsapp_send": "whatsapp_api_direct",
    "telegram_read": "telegram_bot_api_direct",
    "telegram_send": "telegram_bot_api_direct",
    "calendar_inspect_availability": "google_calendar_legacy_adapter",
    "calendar_propose_event": "google_calendar_legacy_adapter",
    "calendar_create_event": "google_calendar_legacy_adapter",
    "calendar_update_event": "google_calendar_legacy_adapter",
    "calendar_delete_event": "google_calendar_legacy_adapter",
    "search_web": "search_legacy_adapter",
}

_EXTERNAL_SIDE_EFFECT_TOOLS = {
    "email_send",
    "whatsapp_send",
    "telegram_send",
    "calendar_create_event",
    "calendar_update_event",
    "calendar_delete_event",
    "search_web",
}

_DESTRUCTIVE_TOOLS = {"calendar_delete_event"}


def get_mcp_gateway_tool_metadata() -> List[ToolMetadata]:
    """Returns transitional local-adapter metadata plus discovered provider-managed MCP metadata."""
    metadata: List[ToolMetadata] = []
    for tool in ALL_MCP_TOOLS + ALL_EXTERNAL_API_TOOLS:
        if is_removed_tool_name(tool.name):
            continue
        risk_class = get_mcp_tool_risk(tool.name)
        metadata.append(
            ToolMetadata(
                tool_id=(
                    f"external_api.{_PROVIDER_FOR_TOOL.get(tool.name)}.{normalize_tool_id_part(tool.name)}"
                    if _PROVIDER_FOR_TOOL.get(tool.name) in {"whatsapp_api", "telegram_bot_api"}
                    else f"mcp.gateway_legacy.{normalize_tool_id_part(tool.name)}"
                ),
                legacy_name=tool.name,
                display_name=tool.name.replace("_", " ").title(),
                provider=_PROVIDER_FOR_TOOL.get(tool.name, "mcp_gateway"),
                category=_MCP_GATEWAY_TOOL_CATEGORIES.get(tool.name, "provider_managed_mcp"),
                implementation_type=ImplementationType.EXTERNAL_API if _PROVIDER_FOR_TOOL.get(tool.name) in {"whatsapp_api", "telegram_bot_api"} else ImplementationType.MCP,
                enabled=_is_tool_provider_available(tool.name),
                availability_status=AvailabilityStatus.AVAILABLE if _is_tool_provider_available(tool.name) else AvailabilityStatus.UNAVAILABLE,
                risk_class=risk_class,
                approval_policy=approval_policy_for_risk(risk_class),
                read_write_capability=infer_read_write_capability(tool.name),
                external_side_effect=tool.name in _EXTERNAL_SIDE_EFFECT_TOOLS,
                destructive=tool.name in _DESTRUCTIVE_TOOLS,
                scheduled_capable=False,
                provider_managed=False if _PROVIDER_FOR_TOOL.get(tool.name) in {"whatsapp_api", "telegram_bot_api"} else True,
                input_schema=schema_from_langchain_tool(tool),
                output_schema_hint="text",
                observability_metadata={
                    "migration_phase": "direct_api_change" if _PROVIDER_FOR_TOOL.get(tool.name) in {"whatsapp_api", "telegram_bot_api"} else "T7",
                    "compatibility_wrapper": True,
                    "legacy_local_adapter_backed": False,
                    "provider_managed_target": False if _PROVIDER_FOR_TOOL.get(tool.name) in {"whatsapp_api", "telegram_bot_api"} else True,
                    "registry_source": "src.mcp_gateway.registry",
                },
            )
        )
    metadata.extend(get_provider_managed_mcp_tool_metadata(refresh=False))
    return metadata









