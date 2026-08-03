import pytest
from fastapi.testclient import TestClient
from src.db import init_db, get_connection
from src.mcp_gateway.calendar import (
    calendar_inspect_availability,
    calendar_propose_event,
    calendar_create_event,
    calendar_update_event,
    calendar_delete_event,
    detect_calendar_conflicts
)
from src.mcp_gateway.google_calendar_sync import GoogleCalendarSyncProvider
from src.api.server import app

@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_p4_calendar.db"
    mem_file = tmp_path / "MEMORY.md"

    monkeypatch.setattr("src.db.DB_PATH", db_file)
    monkeypatch.setattr("src.config.MEMORY_PATH", mem_file)
    init_db(db_file)
    return db_file

client = TestClient(app)

def test_calendar_crud_tools_and_conflict_detection(temp_db):
    """Verifies calendar CRUD tool functions and automatic conflict detection."""
    # 1. Propose event 1
    res1 = calendar_propose_event.invoke({"title": "Design Sprint", "start_time": "2026-08-10 10:00", "end_time": "2026-08-10 11:00"})
    assert "Design Sprint" in res1
    assert "evt_" in res1

    # Extract event ID
    evt_id1 = res1.split("(ID: ")[1].split(")")[0]

    # 2. Propose overlapping event 2 (conflict expected)
    res2 = calendar_propose_event.invoke({"title": "Architecture Sync", "start_time": "2026-08-10 10:30", "end_time": "2026-08-10 11:30"})
    assert "CONFLICT WARNING" in res2
    assert "Design Sprint" in res2

    # 3. Update event 1 to non-overlapping time
    res_upd = calendar_update_event.invoke({
        "event_id": evt_id1,
        "title": "Design Sprint (Shifted)",
        "start_time": "2026-08-10 08:00",
        "end_time": "2026-08-10 09:00",
        "status": "CONFIRMED"
    })
    assert "UPDATED" in res_upd

    # Inspect availability
    res_insp = calendar_inspect_availability.invoke({"start_date": "2026-08-10 00:00", "end_date": "2026-08-10 23:59"})
    assert "Design Sprint (Shifted)" in res_insp
    assert "Architecture Sync" in res_insp

    # 4. Delete event 1
    res_del = calendar_delete_event.invoke({"event_id": evt_id1})
    assert "DELETED" in res_del

def test_calendar_rest_api_endpoints(temp_db):
    """Verifies Calendar REST API endpoints GET/POST/PUT/DELETE /api/calendar/events."""
    # POST create event
    resp_post = client.post("/api/calendar/events", json={
        "title": "Q3 Planning",
        "start_time": "2026-09-01 14:00",
        "end_time": "2026-09-01 15:00",
        "location": "Conf Room A"
    })
    assert resp_post.status_code == 200
    assert resp_post.json()["status"] == "APPROVAL_REQUIRED"

    # GET events
    resp_get = client.get("/api/calendar/events")
    assert resp_get.status_code == 200

    # DELETE event
    resp_del = client.delete("/api/calendar/events/evt_123")
    assert resp_del.status_code == 200
    assert resp_del.json()["status"] == "APPROVAL_REQUIRED"


def test_google_calendar_sync_fallback(temp_db):
    """Verifies GoogleCalendarSyncProvider graceful fallback in local-first mode."""
    provider = GoogleCalendarSyncProvider()
    res_push = provider.sync_local_to_google()
    assert res_push["status"] == "local_only"

    res_pull = provider.sync_google_to_local()
    assert res_pull["status"] == "local_only"
