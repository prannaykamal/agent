import pytest
from src.db import init_db, get_connection
from src.mcp_gateway.calendar import (
    calendar_inspect_availability,
    calendar_propose_event,
    calendar_create_event
)
from src.mcp_gateway.communication import (
    email_draft,
    email_read,
    email_search,
    email_send,
    whatsapp_read,
    whatsapp_send,
    telegram_read,
    telegram_send
)
from src.mcp_gateway.search import search_web

@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_real_tools.db"
    mem_file = tmp_path / "MEMORY.md"

    monkeypatch.setattr("src.db.DB_PATH", db_file)
    monkeypatch.setattr("src.config.MEMORY_PATH", mem_file)
    init_db(db_file)
    return db_file

def test_real_calendar_events(temp_db):
    res_prop = calendar_propose_event.invoke({"title": "Design Sync", "start_time": "2026-08-01 10:00", "end_time": "2026-08-01 11:00"})
    assert "PROPOSAL" in res_prop or "PROPOSED" in res_prop

    res_create = calendar_create_event.invoke({"title": "Sprint Planning", "start_time": "2026-08-01 14:00", "end_time": "2026-08-01 15:00"})
    assert "CREATED" in res_create

    res_inspect = calendar_inspect_availability.invoke({"start_date": "2026-08-01 00:00", "end_date": "2026-08-01 23:59"})
    assert "Sprint Planning" in res_inspect
    assert "Design Sync" in res_inspect

def test_real_email_messaging(temp_db):
    draft_res = email_draft.invoke({"to": "alice@company.com", "subject": "Quarterly Report", "body": "Draft report content"})
    assert "draft saved" in draft_res.lower()


    send_res = email_send.invoke({"to": "bob@company.com", "subject": "Project Status", "body": "Status update content"})
    assert "SENT" in send_res

    read_res = email_read.invoke({"limit": 5})
    assert "Quarterly Report" in read_res or "Project Status" in read_res

    search_res = email_search.invoke({"query": "Quarterly"})
    assert "Quarterly Report" in search_res

    wa_res = whatsapp_send.invoke({"recipient": "+1234567890", "message": "Meeting at 3pm"})
    assert "SENT" in wa_res
    assert "Meeting at 3pm" in whatsapp_read.invoke({"limit": 5})

    tg_res = telegram_send.invoke({"chat_id": "team_chat", "text": "Deployment completed"})
    assert "SENT" in tg_res
    assert "Deployment completed" in telegram_read.invoke({"limit": 5})

def test_live_web_search(temp_db):
    res = search_web.invoke({"query": "Python 3.12", "max_results": 2})
    assert "Python" in res
    assert "Source:" in res
