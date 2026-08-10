import pytest
from fastapi.testclient import TestClient

from src.api.server import app
from src.db import init_db


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_t5_api.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file


client = TestClient(app)


def test_t5_cron_schedule_api_lifecycle(temp_db):
    create = client.post("/api/tools/cron/schedules", json={
        "schedule_type": "one_time",
        "run_at": "2026-08-10 09:00",
        "timezone": "UTC",
        "target_tool_id": "heartbeat",
        "target_payload": {"api_token": "secret", "note": "hello"},
    })
    assert create.status_code == 200
    schedule = create.json()["schedule"]
    schedule_id = schedule["id"]
    assert schedule["next_run_at"] == "2026-08-10T09:00:00Z"

    listed = client.get("/api/tools/cron/schedules")
    assert listed.status_code == 200
    listed_schedule = listed.json()["schedules"][0]
    assert listed_schedule["target_payload"]["api_token"] == "[REDACTED]"

    get_one = client.get(f"/api/tools/cron/schedules/{schedule_id}")
    assert get_one.status_code == 200

    patch = client.patch(f"/api/tools/cron/schedules/{schedule_id}", json={"run_at": "2026-08-10 10:00"})
    assert patch.status_code == 200
    assert patch.json()["schedule"]["next_run_at"] == "2026-08-10T10:00:00Z"

    runs = client.get("/api/tools/cron/runs")
    assert runs.status_code == 200
    assert "runs" in runs.json()

    delete = client.delete(f"/api/tools/cron/schedules/{schedule_id}")
    assert delete.status_code == 200
    assert delete.json()["schedule"]["status"] == "CANCELLED"


def test_t5_cron_api_rejects_invalid_cron(temp_db):
    response = client.post("/api/tools/cron/schedules", json={
        "schedule_type": "recurring",
        "cron_expression": "bad cron",
        "target_tool_id": "heartbeat",
    })
    assert response.status_code == 400


def test_t5_update_that_increases_risk_fails_closed(temp_db):
    created = client.post("/api/tools/cron/schedules", json={"schedule_type": "one_time", "run_at": "2026-08-10 09:00", "target_tool_id": "heartbeat"})
    schedule_id = created.json()["schedule"]["id"]
    response = client.patch(f"/api/tools/cron/schedules/{schedule_id}", json={"target_tool_id": "email_send"})
    assert response.status_code == 403


def test_t5_legacy_api_scheduled_wrapper_still_works(temp_db):
    create = client.post("/api/scheduled", json={"cron_or_timestamp": "2026-08-10 09:00", "task_payload": "legacy payload"})
    assert create.status_code == 200
    listed = client.get("/api/scheduled")
    assert listed.status_code == 200
    job = listed.json()["scheduled_jobs"][0]
    assert job["task_payload"] == "legacy payload"
    delete = client.delete(f"/api/scheduled/{job['id']}")
    assert delete.status_code == 200
