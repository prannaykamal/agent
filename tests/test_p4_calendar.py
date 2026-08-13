import pytest
from fastapi.testclient import TestClient
from src.db import init_db
from src.mcp_gateway.calendar import (
    calendar_inspect_availability,
    calendar_propose_event,
    calendar_create_event,
    calendar_update_event,
    calendar_delete_event,
    detect_calendar_conflicts,
)
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


def test_calendar_tools_use_google_calendar_mcp_unavailable_state(temp_db, monkeypatch):
    from src.tools.mcp_invocation import MCPInvocationResult, MCPInvocationStatus

    monkeypatch.setattr(
        "src.tools.mcp_invocation.invoke_provider_tool",
        lambda *args, **kwargs: MCPInvocationResult(status=MCPInvocationStatus.PROVIDER_UNAVAILABLE),
    )

    assert "Unavailable" in calendar_propose_event.invoke({"title": "Design", "start_time": "10:00", "end_time": "11:00"})
    assert "Unavailable" in calendar_create_event.invoke({"title": "Design", "start_time": "10:00", "end_time": "11:00"})
    assert "Unavailable" in calendar_update_event.invoke({"event_id": "evt_1", "title": "Design", "start_time": "10:00", "end_time": "11:00"})
    assert "Unavailable" in calendar_delete_event.invoke({"event_id": "evt_1"})
    assert "Unavailable" in calendar_inspect_availability.invoke({"start_date": "2026-08-10", "end_date": "2026-08-11"})
    monkeypatch.setattr("src.mcp_gateway.calendar.access_token_from_env", lambda: "")
    assert detect_calendar_conflicts("10:00", "11:00") == []


def test_calendar_rest_api_endpoints_keep_shape(temp_db):
    resp_post = client.post("/api/calendar/events", json={"title": "Q3", "start_time": "14:00", "end_time": "15:00"})
    assert resp_post.status_code == 200
    assert resp_post.json()["status"] == "APPROVAL_REQUIRED"

    resp_get = client.get("/api/calendar/events")
    assert resp_get.status_code == 200
    assert isinstance(resp_get.json()["events"], list)
    assert "result" in resp_get.json()

    resp_del = client.delete("/api/calendar/events/evt_123")
    assert resp_del.status_code == 200
    assert resp_del.json()["status"] == "APPROVAL_REQUIRED"
