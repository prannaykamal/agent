import pytest
from src.db import init_db
from src.mcp_gateway.calendar import calendar_inspect_availability, calendar_propose_event, calendar_create_event
from src.mcp_gateway.communication import email_draft, email_read, email_search, email_send, whatsapp_read, whatsapp_send, telegram_read, telegram_send
from src.mcp_gateway.search import search_web


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_real_tools.db"
    mem_file = tmp_path / "MEMORY.md"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    monkeypatch.setattr("src.config.MEMORY_PATH", mem_file)
    init_db(db_file)
    return db_file


def test_provider_tools_report_unavailable_without_mcp_config(temp_db, monkeypatch):
    from src.tools.mcp_invocation import MCPInvocationResult, MCPInvocationStatus

    monkeypatch.setattr(
        "src.tools.mcp_invocation.invoke_provider_tool",
        lambda *args, **kwargs: MCPInvocationResult(status=MCPInvocationStatus.PROVIDER_UNAVAILABLE),
    )

    tool_results = [
        calendar_propose_event.invoke({"title": "Design", "start_time": "10:00", "end_time": "11:00"}),
        calendar_create_event.invoke({"title": "Sprint", "start_time": "14:00", "end_time": "15:00"}),
        calendar_inspect_availability.invoke({"start_date": "2026-08-01", "end_date": "2026-08-02"}),
        email_draft.invoke({"to": "alice@company.com", "subject": "Quarterly", "body": "Draft"}),
        email_send.invoke({"to": "bob@company.com", "subject": "Status", "body": "Update"}),
        email_read.invoke({"limit": 5}),
        email_search.invoke({"query": "Quarterly"}),
        whatsapp_send.invoke({"recipient": "+123", "message": "Meeting"}),
        whatsapp_read.invoke({"limit": 5}),
        telegram_send.invoke({"chat_id": "team", "text": "Done"}),
        telegram_read.invoke({"limit": 5}),
        search_web.invoke({"query": "Python", "max_results": 2}),
    ]

    assert all("Unavailable" in result for result in tool_results)
