from src.mcp_gateway.communication import (
    email_read, email_search, email_draft, email_send,
    whatsapp_read, whatsapp_send,
    telegram_read, telegram_send,
)
from src.mcp_gateway.calendar import calendar_inspect_availability, calendar_propose_event, calendar_create_event
from src.mcp_gateway.search import search_web
from src.mcp_gateway.registry import get_all_mcp_tools, get_mcp_tool_risk


def test_communication_mcp_tools_report_unavailable_without_provider():
    assert "Unavailable" in email_read.invoke({"limit": 2})
    assert "Unavailable" in email_search.invoke({"query": "invoice"})
    assert "Unavailable" in email_draft.invoke({"to": "user@example.com", "subject": "Test", "body": "Draft"})
    assert "Unavailable" in email_send.invoke({"to": "user@example.com", "subject": "Test", "body": "Send"})
    assert "Unavailable" in whatsapp_send.invoke({"recipient": "+1234567890", "message": "Hello"})
    assert "Unavailable" in telegram_send.invoke({"chat_id": "12345", "text": "Ping"})


def test_calendar_mcp_tools_report_unavailable_without_provider():
    assert "Unavailable" in calendar_inspect_availability.invoke({"start_date": "2026-08-01", "end_date": "2026-08-02"})
    assert "Unavailable" in calendar_propose_event.invoke({"title": "Design Review", "start_time": "10:00", "end_time": "11:00"})
    assert "Unavailable" in calendar_create_event.invoke({"title": "Design Review", "start_time": "10:00", "end_time": "11:00"})


def test_search_mcp_tool_reports_unavailable_without_provider():
    search_res = search_web.invoke({"query": "Python 3.12 features"})
    assert "Unavailable" in search_res


def test_mcp_registry_and_risk(monkeypatch):
    monkeypatch.setattr("src.mcp_gateway.registry.load_live_mcp_tools", lambda: [])
    all_tools = get_all_mcp_tools()
    tool_names = [t.name for t in all_tools]

    assert "email_send" not in tool_names
    assert "calendar_create_event" not in tool_names
    assert "search_web" not in tool_names
    assert "run_code" not in tool_names
    assert "github_clone" not in tool_names
    assert "github_commit_and_push" not in tool_names
    assert "github_merge" not in tool_names
    assert "safe_browse_url" not in tool_names
    assert "capture_screenshot" not in tool_names

    assert get_mcp_tool_risk("email_send") == "High"
    assert get_mcp_tool_risk("whatsapp_send") == "High"
    assert get_mcp_tool_risk("calendar_create_event") == "High"
    assert get_mcp_tool_risk("github_merge") == "Blocked"
    assert get_mcp_tool_risk("search_web") == "Low"
    assert get_mcp_tool_risk("run_code") == "Blocked"
