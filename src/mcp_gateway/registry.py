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
    Returns all registered MCP gateway tools for LangChain/LangGraph binding,
    combining native tools with live MCP tools loaded from Stdio/SSE servers.
    """
    live_tools = load_live_mcp_tools()
    return ALL_MCP_TOOLS + live_tools

def get_mcp_tool_risk(tool_name: str) -> str:
    """Returns the risk level ('Low', 'Medium', 'High') for a tool by name."""
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


