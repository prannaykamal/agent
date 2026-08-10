import pytest

from src.db import init_db
from src.personal_os.scheduler_store import ToolScheduleRepository, ToolScheduleWrite


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_t5_repo.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file


def test_t5_one_time_schedule_persists_and_cancels(temp_db):
    repo = ToolScheduleRepository(temp_db)
    schedule = repo.create_schedule(ToolScheduleWrite(schedule_type="one_time", run_at="2026-08-10 09:00", timezone="UTC", target_tool_id="heartbeat", target_payload={"ok": True}))
    assert schedule.schedule_type == "one_time"
    assert schedule.next_run_at == "2026-08-10T09:00:00Z"
    assert schedule.status == "ACTIVE"
    cancelled = repo.cancel_schedule(schedule.id)
    assert cancelled.status == "CANCELLED"


def test_t5_recurring_schedule_next_run_and_update(temp_db):
    repo = ToolScheduleRepository(temp_db)
    schedule = repo.create_schedule(ToolScheduleWrite(schedule_type="recurring", cron_expression="*/30 * * * *", timezone="UTC", target_tool_id="heartbeat", target_payload={}), now="2026-08-10T09:01:00Z")
    assert schedule.next_run_at == "2026-08-10T09:30:00Z"
    updated = repo.update_schedule(schedule.id, {"cron_expression": "0 10 * * *"}, now="2026-08-10T09:01:00Z")
    assert updated.next_run_at == "2026-08-10T10:00:00Z"


def test_t5_run_idempotency_for_same_occurrence(temp_db):
    repo = ToolScheduleRepository(temp_db)
    schedule = repo.create_schedule(ToolScheduleWrite(schedule_type="one_time", run_at="2026-08-10 09:00", timezone="UTC", target_tool_id="heartbeat", target_payload={}))
    run1 = repo.create_or_get_run(schedule.id, schedule.next_run_at)
    run2 = repo.create_or_get_run(schedule.id, schedule.next_run_at)
    assert run1.id == run2.id
