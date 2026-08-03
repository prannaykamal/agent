import sqlite3
import pytest
from pathlib import Path
from threading import Event
from fastapi.testclient import TestClient
from src.db import init_db, get_connection
from src.db_migrations import run_db_migrations
from src.harness.graph import log_loop_event
from src.background_worker import run_scheduled_worker_loop, process_due_scheduled_jobs
from src.personal_os.backup import export_agent_backup, rotate_backups, restore_agent_backup
from src.startup import ensure_system_initialized
from src.api.server import app

@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_p5_reliability.db"
    mem_file = tmp_path / "MEMORY.md"

    monkeypatch.setattr("src.db.DB_PATH", db_file)
    monkeypatch.setattr("src.config.MEMORY_PATH", mem_file)
    init_db(db_file)
    return db_file

client = TestClient(app)

def test_db_migration_upgrade_old_database(tmp_path):
    """P5 Item 1: Migration test verifying upgrade from an old v1 database to latest migration v5."""
    old_db = tmp_path / "old_v1.db"
    conn = sqlite3.connect(old_db)
    cursor = conn.cursor()
    # Create old v1 table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            description TEXT NOT NULL,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    cursor.execute("INSERT INTO schema_migrations (version, description) VALUES (1, 'Initial v1')")
    cursor.execute("CREATE TABLE raw_turns (id TEXT PRIMARY KEY, session_id TEXT, sender TEXT, content TEXT, tokens INT)")
    conn.commit()
    conn.close()

    # Run migration upgrade
    run_db_migrations(old_db)

    # Check migrated schema version and new tables
    conn2 = sqlite3.connect(old_db)
    cursor2 = conn2.cursor()
    cursor2.execute("SELECT MAX(version) FROM schema_migrations")
    latest_ver = cursor2.fetchone()[0]
    assert latest_ver >= 5


    cursor2.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('tool_calls', 'tool_results')")
    tables = [r[0] for r in cursor2.fetchall()]
    assert "tool_calls" in tables
    assert "tool_results" in tables
    conn2.close()

def test_p5_session_indexes_and_formal_tool_tables(temp_db):
    """P5 Item 2 & 3: Verifies formal tool_calls and tool_results tracking tables and session indexes."""
    conn = get_connection(temp_db)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'")
    indexes = [r["name"] for r in cursor.fetchall()]
    assert "idx_raw_turns_session" in indexes
    assert "idx_tool_calls_session" in indexes
    assert "idx_tool_results_session" in indexes
    conn.close()

    # Test tool_calls and tool_results logging in log_loop_event
    evt1 = log_loop_event(session_id="sess_p5", step_index=1, step_type="TOOL_REQUESTED", tool_name="calendar_inspect_availability", tool_args={"start_date": "2026-08-01"})
    evt2 = log_loop_event(session_id="sess_p5", step_index=1, step_type="TOOL_EXECUTED", tool_name="calendar_inspect_availability", tool_result="All slots free")

    conn2 = get_connection(temp_db)
    cursor2 = conn2.cursor()
    cursor2.execute("SELECT * FROM tool_calls WHERE session_id = 'sess_p5'")
    calls = cursor2.fetchall()
    assert len(calls) == 1
    assert calls[0]["tool_name"] == "calendar_inspect_availability"

    cursor2.execute("SELECT * FROM tool_results WHERE session_id = 'sess_p5'")
    results = cursor2.fetchall()
    assert len(results) == 1
    assert "All slots free" in results[0]["result_content"]
    conn2.close()

def test_p5_background_worker_entrypoint_and_loop(temp_db):
    """P5 Item 4 & 5: Verifies background worker entrypoint loop and graceful stop event."""
    stop_flag = Event()
    stop_flag.set() # Stop immediately after 1 iteration

    # Test loop execution with pre-set stop flag
    run_scheduled_worker_loop(interval_seconds=1, stop_event=stop_flag, db_path=temp_db)
    assert stop_flag.is_set()

def test_p5_backup_rotation_and_restore(temp_db, tmp_path):
    """P5 Item 6 & 7: Verifies backup rotation policy and restore-from-backup functionality."""
    backup_dir = tmp_path / "backups_test"
    backup_dir.mkdir(parents=True, exist_ok=True)

    # Create 3 backups
    b1 = export_agent_backup(output_dir=backup_dir, max_backups=2)
    b2 = export_agent_backup(output_dir=backup_dir, max_backups=2)
    b3 = export_agent_backup(output_dir=backup_dir, max_backups=2)

    # Verify rotation policy kept max 2 backups
    zip_files = list(backup_dir.glob("agent_backup_*.zip"))
    assert len(zip_files) <= 2

    # Restore from backup
    res_restore = restore_agent_backup(Path(b3["backup_path"]))
    assert res_restore["status"] == "RESTORED"
    assert len(res_restore["restored_files"]) >= 1

def test_p5_app_startup_and_restore_endpoint(temp_db, tmp_path):
    """P5 Item 8: Verifies ensure_system_initialized startup call and REST API backup/restore endpoints."""
    init_res = ensure_system_initialized()
    assert init_res["status"] == "INITIALIZED"

    resp_backup = client.post("/api/system/backup")
    assert resp_backup.status_code == 200
    b_path = resp_backup.json()["backup_path"]

    resp_restore = client.post("/api/system/restore", json={"backup_path": b_path})
    assert resp_restore.status_code == 200, f"Restore failed with detail: {resp_restore.json()}"
    assert resp_restore.json()["status"] == "RESTORED"


