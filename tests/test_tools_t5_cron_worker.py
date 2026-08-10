import sqlite3

import pytest

from src.db import get_connection, init_db
from src.personal_os.scheduler_service import create_tool_schedule
from src.personal_os.scheduler_store import ToolScheduleRepository
from src.personal_os.scheduler_worker import process_due_schedules_once, process_due_tool_schedules


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_t5_worker.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file


def test_t5_due_one_time_read_only_schedule_executes_once(temp_db):
    result = create_tool_schedule(schedule_type="one_time", run_at="2026-08-10 09:00", timezone="UTC", target_tool_id="heartbeat", target_payload={}, db_path=temp_db)
    processed = process_due_schedules_once(db_path=temp_db, now="2026-08-10T09:01:00Z")
    assert len(processed) == 1
    assert processed[0]["status"] == "SUCCEEDED"
    repo = ToolScheduleRepository(temp_db)
    schedule = repo.get_schedule(result.schedule.id)
    assert schedule.status == "COMPLETED"
    assert process_due_schedules_once(db_path=temp_db, now="2026-08-10T09:02:00Z") == []


def test_t5_cancelled_schedule_does_not_execute(temp_db):
    result = create_tool_schedule(schedule_type="one_time", run_at="2026-08-10 09:00", timezone="UTC", target_tool_id="heartbeat", target_payload={}, db_path=temp_db)
    ToolScheduleRepository(temp_db).cancel_schedule(result.schedule.id)
    assert process_due_schedules_once(db_path=temp_db, now="2026-08-10T09:01:00Z") == []


def test_t5_recurring_schedule_advances_after_success(temp_db):
    result = create_tool_schedule(schedule_type="recurring", cron_expression="*/5 * * * *", timezone="UTC", target_tool_id="heartbeat", target_payload={}, db_path=temp_db, now="2026-08-10T09:00:00Z")
    processed = process_due_schedules_once(db_path=temp_db, now="2026-08-10T09:05:00Z")
    assert len(processed) == 1
    schedule = ToolScheduleRepository(temp_db).get_schedule(result.schedule.id)
    assert schedule.last_run_at == "2026-08-10T09:05:00Z"
    assert schedule.next_run_at == "2026-08-10T09:10:00Z"


def test_t5_high_risk_schedule_waits_for_approval_without_execution(temp_db):
    result = create_tool_schedule(schedule_type="one_time", run_at="2026-08-10 09:00", timezone="UTC", target_tool_id="email_send", target_payload={"recipient": "a@example.com", "body": "hi"}, db_path=temp_db)
    processed = process_due_schedules_once(db_path=temp_db, now="2026-08-10T09:01:00Z")
    assert processed[0]["status"] == "WAITING_FOR_APPROVAL"
    assert processed[0]["approval_request_id"]
    conn = get_connection(temp_db)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) AS count FROM emails")
    assert cursor.fetchone()["count"] == 0
    conn.close()


def test_t5_retryable_failure_then_terminal(monkeypatch, temp_db):
    import src.personal_os.scheduler_worker as worker

    result = create_tool_schedule(schedule_type="one_time", run_at="2026-08-10 09:00", timezone="UTC", target_tool_id="heartbeat", target_payload={}, db_path=temp_db)

    def boom(schedule):
        raise RuntimeError("temporary failure")

    monkeypatch.setattr(worker, "_invoke_direct_tool", boom)
    first = process_due_schedules_once(db_path=temp_db, now="2026-08-10T09:01:00Z")
    second = process_due_schedules_once(db_path=temp_db, now="2026-08-10T09:02:00Z")
    third = process_due_schedules_once(db_path=temp_db, now="2026-08-10T09:03:00Z")
    assert first[0]["status"] == "FAILED_RETRYABLE"
    assert second[0]["status"] == "FAILED_RETRYABLE"
    assert third[0]["status"] == "FAILED_TERMINAL"


def test_t5_missed_run_skip_policy_advances_without_run(temp_db):
    result = create_tool_schedule(schedule_type="recurring", cron_expression="0 9 * * *", timezone="UTC", target_tool_id="email_send", target_payload={}, missed_run_policy="skip", db_path=temp_db, now="2026-08-10T08:00:00Z")
    processed = process_due_tool_schedules(db_path=temp_db, now="2026-08-11T10:00:00Z")
    assert processed == []
    schedule = ToolScheduleRepository(temp_db).get_schedule(result.schedule.id)
    assert schedule.next_run_at > "2026-08-11T10:00:00Z"


def test_t5_catch_up_limited_respects_limit(temp_db):
    result = create_tool_schedule(schedule_type="recurring", cron_expression="* * * * *", timezone="UTC", target_tool_id="heartbeat", target_payload={}, missed_run_policy="catch_up_limited", max_catchup_runs=2, db_path=temp_db, now="2026-08-10T09:00:00Z")
    processed = process_due_schedules_once(db_path=temp_db, now="2026-08-10T09:05:00Z")
    assert len(processed) == 2
    runs = ToolScheduleRepository(temp_db).list_runs(schedule_id=result.schedule.id)
    assert len(runs) == 2
