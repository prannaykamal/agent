import json

from src.mcp_gateway.calendar_api import (
    CALENDAR_API_ROOT,
    SIGN_IN_REQUIRED,
    CalendarApiError,
    CalendarClient,
    parse_datetime,
)
from src.mcp_gateway.calendar_local_mcp import TOOLS, handle_rpc
from src.mcp_gateway.protocol.oauth import stdio_env_with_oauth


def test_parse_datetime_accepts_iso_and_clock_times():
    parsed = parse_datetime("2026-08-15T05:00:00")
    assert parsed.year == 2026
    assert parsed.month == 8
    assert parsed.day == 15
    assert parsed.hour == 5
    clock = parse_datetime("05:00")
    assert clock.hour == 5
    assert clock.minute == 0


def test_calendar_create_event_posts_primary_calendar():
    captured = {}

    def fake_request(method, url, headers, body):
        captured["method"] = method
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = json.loads(body.decode("utf-8"))
        return {"id": "evt-1", "summary": "Meeting", "htmlLink": "https://calendar.google.com/event?eid=evt-1"}

    client = CalendarClient("ya29-test", request_fn=fake_request)
    text = client.create_event("Meeting", "2026-08-15T05:00:00", "2026-08-15T06:00:00")
    assert captured["method"] == "POST"
    assert captured["url"] == f"{CALENDAR_API_ROOT}/calendars/primary/events"
    assert captured["headers"]["Authorization"] == "Bearer ya29-test"
    assert captured["body"]["summary"] == "Meeting"
    assert captured["body"]["start"]["dateTime"].startswith("2026-08-15T05:00:00")
    assert "Created calendar event 'Meeting'" in text
    assert "evt-1" in text


def test_calendar_list_events_uses_time_window():
    def fake_request(method, url, headers, body):
        assert method == "GET"
        assert url.startswith(f"{CALENDAR_API_ROOT}/calendars/primary/events?")
        assert "timeMin=" in url
        assert "timeMax=" in url
        return {
            "items": [
                {
                    "id": "evt-2",
                    "summary": "Standup",
                    "start": {"dateTime": "2026-08-15T09:00:00+05:30"},
                    "end": {"dateTime": "2026-08-15T09:30:00+05:30"},
                }
            ]
        }

    client = CalendarClient("token", request_fn=fake_request)
    listed = client.list_events("2026-08-15T00:00:00", "2026-08-16T00:00:00")
    assert "Standup" in listed
    assert "evt-2" in listed


def test_calendar_find_conflicts_returns_overlapping_events():
    def fake_request(method, url, headers, body):
        return {
            "items": [
                {
                    "id": "evt-busy",
                    "summary": "Busy",
                    "start": {"dateTime": "2026-08-15T09:00:00+05:30"},
                    "end": {"dateTime": "2026-08-15T10:00:00+05:30"},
                },
                {
                    "id": "evt-other",
                    "summary": "Later",
                    "start": {"dateTime": "2026-08-15T11:00:00+05:30"},
                    "end": {"dateTime": "2026-08-15T12:00:00+05:30"},
                },
            ]
        }

    client = CalendarClient("token", request_fn=fake_request)
    conflicts = client.find_conflicts("2026-08-15T09:30:00+05:30", "2026-08-15T10:30:00+05:30")
    assert len(conflicts) == 1
    assert conflicts[0]["id"] == "evt-busy"
    assert conflicts[0]["title"] == "Busy"


def test_calendar_missing_token_asks_for_sign_in():
    client = CalendarClient("")
    try:
        client.list_events()
        raise AssertionError("expected CalendarApiError")
    except CalendarApiError as exc:
        assert exc.status == 401
        assert str(exc) == SIGN_IN_REQUIRED


def test_local_mcp_lists_personal_calendar_tools():
    response = handle_rpc({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    names = [item["name"] for item in response["result"]["tools"]]
    assert names == ["create_event", "update_event", "delete_event", "list_events"]
    assert {item["name"] for item in TOOLS} == set(names)


def test_local_mcp_create_event_uses_calendar_client():
    class FakeClient:
        def create_event(self, title, start_time, end_time, attendees, location):
            return f"Created calendar event '{title}' from {start_time} to {end_time}."

    response = handle_rpc(
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {
                "name": "create_event",
                "arguments": {"title": "Meeting", "start_time": "2026-08-15T05:00:00", "end_time": "2026-08-15T06:00:00"},
            },
        },
        client=FakeClient(),
    )
    assert response["result"]["isError"] is False
    assert "Meeting" in response["result"]["content"][0]["text"]


def test_stdio_env_injects_calendar_access_token(tmp_path):
    env = stdio_env_with_oauth(
        {"EXISTING": "1"},
        {"accessToken": "ya29-injected"},
        project_root=tmp_path,
    )
    assert env["CALENDAR_ACCESS_TOKEN"] == "ya29-injected"
    assert env["GOOGLE_ACCESS_TOKEN"] == "ya29-injected"


def test_calendar_stdio_provider_gets_oauth_token_in_env():
    from src.tools.mcp_provider_config import MCPProviderConfig, MCPTransportType
    from src.tools.mcp_provider_registry import _provider_stdio_env

    env = _provider_stdio_env(
        MCPProviderConfig(
            provider_id="google_calendar",
            display_name="Google Calendar MCP",
            transport_type=MCPTransportType.STDIO,
            oauth={"accessToken": "ya29-calendar"},
        )
    )
    assert env["CALENDAR_ACCESS_TOKEN"] == "ya29-calendar"
    assert env["GOOGLE_ACCESS_TOKEN"] == "ya29-calendar"


def test_calendar_create_guidance_includes_today():
    from src.harness.graph import _tool_use_guidance

    class Tool:
        name = "calendar_create_event"

    text = _tool_use_guidance([Tool()])
    assert "calendar_create_event" in text
    assert "2023" not in text or "Never use a past year such as 2023" in text
    assert "Today is" in text
