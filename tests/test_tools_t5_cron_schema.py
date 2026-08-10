import sqlite3

import pytest

from src.db import get_connection, init_db
from src.db_migrations import run_db_migrations


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_t5_schema.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file


def test_t5_fresh_db_creates_scheduler_tables(temp_db):
    conn = get_connection(temp_db)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('tool_schedules', 'tool_schedule_runs', 'scheduled_jobs')")
    tables = {row["name"] for row in cursor.fetchall()}
    cursor.execute("SELECT MAX(version) AS version FROM schema_migrations")
    version = cursor.fetchone()["version"]
    conn.close()
    assert {"tool_schedules", "tool_schedule_runs", "scheduled_jobs"}.issubset(tables)
    assert version >= 9


def test_t5_migration_is_idempotent_and_preserves_legacy_scheduled_jobs(temp_db):
    conn = get_connection(temp_db)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO scheduled_jobs (id, cron_or_timestamp, task_payload, status) VALUES ('legacy_1', '2026-01-01 00:00', 'legacy payload', 'PENDING')")
    conn.commit()
    conn.close()

    run_db_migrations(temp_db)
    run_db_migrations(temp_db)

    conn = get_connection(temp_db)
    cursor = conn.cursor()
    cursor.execute("SELECT task_payload FROM scheduled_jobs WHERE id = 'legacy_1'")
    assert cursor.fetchone()["task_payload"] == "legacy payload"
    cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND name = 'idx_tool_schedules_status_next'")
    assert cursor.fetchone() is not None
    conn.close()


def test_t5_memory_jobs_not_used_for_schedule_definitions(temp_db):
    conn = get_connection(temp_db)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(memory_jobs)")
    columns = {row["name"] for row in cursor.fetchall()}
    conn.close()
    assert "cron_expression" not in columns
    assert "next_run_at" not in columns
    assert "target_tool_id" not in columns
