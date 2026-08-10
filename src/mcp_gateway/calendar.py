from typing import Any, Dict, List

from langchain_core.tools import tool

from src.tools import mcp_invocation

_PROVIDER = "google_calendar"


def is_google_calendar_credentials_configured() -> bool:
    """Compatibility helper: reports whether Google Calendar MCP is currently available."""
    from src.tools.mcp_provider_registry import get_mcp_provider_status

    status = get_mcp_provider_status(_PROVIDER) or {}
    return status.get("availability_status") == "available"


def detect_calendar_conflicts(start_time: str, end_time: str, exclude_id: str = "") -> List[Dict[str, Any]]:
    """Legacy compatibility helper. T7 no longer treats local tables as provider source of truth."""
    return []


def _invoke_calendar(tool_hints, args, label):
    result = mcp_invocation.invoke_provider_tool(
        provider_ids=(_PROVIDER,),
        tool_hints=tool_hints,
        arguments=args,
    )
    return result.to_text(label)


@tool
def calendar_inspect_availability(start_date: str, end_date: str) -> str:
    """Inspects calendar availability through Google Calendar MCP only."""
    return _invoke_calendar(
        ("availability", "list", "read", "events"),
        {"start_date": start_date, "end_date": end_date},
        "Google Calendar MCP",
    )


@tool
def calendar_propose_event(title: str, start_time: str, end_time: str, attendees: str = "", location: str = "") -> str:
    """Proposes a calendar event through Google Calendar MCP only, if provider exposes the capability."""
    return _invoke_calendar(
        ("propose", "create", "event"),
        {"title": title, "start_time": start_time, "end_time": end_time, "attendees": attendees, "location": location},
        "Google Calendar MCP",
    )


@tool
def calendar_create_event(title: str, start_time: str, end_time: str, attendees: str = "", location: str = "") -> str:
    """Creates a calendar event through Google Calendar MCP only. Requires HITL approval by policy."""
    return _invoke_calendar(
        ("create", "insert", "event"),
        {"title": title, "start_time": start_time, "end_time": end_time, "attendees": attendees, "location": location},
        "Google Calendar MCP",
    )


@tool
def calendar_update_event(event_id: str, title: str, start_time: str, end_time: str, attendees: str = "", location: str = "", status: str = "CONFIRMED") -> str:
    """Updates a calendar event through Google Calendar MCP only."""
    return _invoke_calendar(
        ("update", "patch", "event"),
        {"event_id": event_id, "title": title, "start_time": start_time, "end_time": end_time, "attendees": attendees, "location": location, "status": status},
        "Google Calendar MCP",
    )


@tool
def calendar_delete_event(event_id: str) -> str:
    """Deletes a calendar event through Google Calendar MCP only. Requires HITL approval by policy."""
    return _invoke_calendar(("delete", "remove", "event"), {"event_id": event_id}, "Google Calendar MCP")
