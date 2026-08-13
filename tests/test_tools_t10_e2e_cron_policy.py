import pytest

from src.db import get_connection, init_db
from src.personal_os.scheduler_service import create_tool_schedule
from src.personal_os.scheduler_store import ToolScheduleRepository
from src.personal_os.scheduler_worker import process_due_schedules_once


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "tools_t10_cron.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file


def _count(table_name):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(f"SELECT COUNT(*) AS count FROM {table_name}")
    value = cursor.fetchone()["count"]
    conn.close()
    return value


def test_t10_read_only_cron_action_runs_without_memory_jobs_definition_storage(temp_db):
    before_memory_jobs = _count("memory_jobs")
    created = create_tool_schedule(
        schedule_type="one_time",
        run_at="2026-08-10 09:00",
        timezone="UTC",
        target_tool_id="heartbeat",
        target_payload={},
        db_path=temp_db,
    )

    processed = process_due_schedules_once(db_path=temp_db, now="2026-08-10T09:01:00Z")

    assert processed[0]["status"] == "SUCCEEDED"
    assert ToolScheduleRepository(temp_db).get_schedule(created.schedule.id).status == "COMPLETED"
    assert _count("tool_schedules") == 1
    assert _count("memory_jobs") == before_memory_jobs


def test_t10_external_scheduled_action_waits_for_approval_without_provider_execution(temp_db):
    created = create_tool_schedule(
        schedule_type="one_time",
        run_at="2026-08-10 09:00",
        timezone="UTC",
        target_tool_id="email_send",
        target_payload={"to": "user@example.com", "body": "Hello"},
        db_path=temp_db,
    )

    processed = process_due_schedules_once(db_path=temp_db, now="2026-08-10T09:01:00Z")

    assert processed[0]["status"] == "WAITING_FOR_APPROVAL"
    run = ToolScheduleRepository(temp_db).list_runs(schedule_id=created.schedule.id)[0]
    assert run.approval_request_id
    assert run.tool_call_id is None
