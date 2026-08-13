from typing import Any, Dict, List

from langchain_core.tools import tool

from src.mcp_gateway.calendar_api import CalendarApiError, CalendarClient, access_token_from_env
from src.tools import mcp_invocation

_PROVIDER = "google_calendar"


def detect_calendar_conflicts(start_time: str, end_time: str, exclude_id: str = "") -> List[Dict[str, Any]]:
    """Return overlapping primary-calendar events for the requested window."""
    token = access_token_from_env()
    if not token:
        return []
    try:
        return CalendarClient(token).find_conflicts(start_time, end_time, exclude_id)
    except CalendarApiError:
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
        ("list_events", "list", "availability", "read"),
        {"start_date": start_date, "end_date": end_date},
        "Google Calendar MCP",
    )


@tool
def calendar_propose_event(title: str, start_time: str, end_time: str, attendees: str = "", location: str = "") -> str:
    """Proposes a calendar event through Google Calendar MCP only, if provider exposes the capability."""
    return _invoke_calendar(
        ("create_event", "create", "insert"),
        {"title": title, "start_time": start_time, "end_time": end_time, "attendees": attendees, "location": location},
        "Google Calendar MCP",
    )


@tool
def calendar_create_event(title: str, start_time: str, end_time: str, attendees: str = "", location: str = "") -> str:
    """Creates a calendar event through Google Calendar MCP only. Requires HITL approval by policy."""
    return _invoke_calendar(
        ("create_event", "create", "insert"),
        {"title": title, "start_time": start_time, "end_time": end_time, "attendees": attendees, "location": location},
        "Google Calendar MCP",
    )


@tool
def calendar_update_event(event_id: str, title: str, start_time: str, end_time: str, attendees: str = "", location: str = "", status: str = "CONFIRMED") -> str:
    """Updates a calendar event through Google Calendar MCP only."""
    return _invoke_calendar(
        ("update_event", "update", "patch"),
        {"event_id": event_id, "title": title, "start_time": start_time, "end_time": end_time, "attendees": attendees, "location": location, "status": status},
        "Google Calendar MCP",
    )


@tool
def calendar_delete_event(event_id: str) -> str:
    """Deletes a calendar event through Google Calendar MCP only. Requires HITL approval by policy."""
    return _invoke_calendar(("delete_event", "delete", "remove"), {"event_id": event_id}, "Google Calendar MCP")
