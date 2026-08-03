import os
import sqlite3
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from src.db import init_db, get_connection, check_tool_call_consistency
from src.db_migrations import run_db_migrations
from src.personal_os.backup import export_agent_backup, restore_agent_backup, rotate_backups, get_available_backups
from src.api.server import app

client = TestClient(app)

@pytest.fixture
def temp_agent_env(tmp_path, monkeypatch):
    agent_dir = tmp_path / ".agent"
    agent_dir.mkdir(parents=True, exist_ok=True)
    db_file = agent_dir / "state.db"
    mem_file = agent_dir / "MEMORY.md"

    monkeypatch.setattr("src.config.AGENT_DIR", agent_dir)
    monkeypatch.setattr("src.config.DB_PATH", db_file)
    monkeypatch.setattr("src.config.MEMORY_PATH", mem_file)
    monkeypatch.setattr("src.db.DB_PATH", db_file)

    init_db(db_file)
    return agent_dir, db_file

def test_p6_1_restore_safety_checks(temp_agent_env, tmp_path):
    """P6 Item 1: Verifies restore safety checks fail on invalid/corrupt zip or missing SQLite header."""
    agent_dir, db_file = temp_agent_env

    # 1. Invalid zip file
    corrupt_zip = tmp_path / "invalid.zip"
    corrupt_zip.write_text("Not a zip file", encoding="utf-8")

    with pytest.raises(ValueError, match="not a valid zip archive"):
        restore_agent_backup(corrupt_zip, db_path=db_file)

    # 2. Corrupt SQLite DB inside zip
    bad_db_zip = tmp_path / "bad_db.zip"
    import zipfile
    with zipfile.ZipFile(bad_db_zip, "w") as zf:
        zf.writestr("state.db", b"Corrupt data without sqlite header")

    with pytest.raises(ValueError, match="Corrupt or invalid SQLite database"):
        restore_agent_backup(bad_db_zip, db_path=db_file)

def test_p6_2_and_3_backup_rotation_and_listing_endpoint(temp_agent_env):
    """P6 Items 2 & 3: Verifies backup rotation policy (max 5) and GET /api/system/backups endpoint."""
    agent_dir, _ = temp_agent_env
    backups_dir = agent_dir / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)

    # Create 7 backup archives
    for i in range(7):
        export_agent_backup(output_dir=backups_dir, max_backups=5)

    remaining = list(backups_dir.glob("agent_backup_*.zip"))
    assert len(remaining) <= 5

    # Test REST API endpoint
    resp = client.get("/api/system/backups")
    assert resp.status_code == 200
    data = resp.json()
    assert "backups" in data
    assert len(data["backups"]) <= 5

def test_p6_5_schema_migration_from_v1(tmp_path):
    """P6 Item 5: Verifies database migration from v1 schema to current v7 schema."""
    old_db = tmp_path / "old_v1.db"
    conn = sqlite3.connect(old_db)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            description TEXT NOT NULL,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    cursor.execute("INSERT INTO schema_migrations (version, description) VALUES (1, 'Initial v1')")
    cursor.execute("CREATE TABLE approval_requests (id TEXT PRIMARY KEY, status TEXT);")
    conn.commit()
    conn.close()

    # Run migration up to v7
    run_db_migrations(old_db)

    # Verify v7 columns idempotency_key and execution_status exist
    conn2 = sqlite3.connect(old_db)
    cursor2 = conn2.cursor()
    cursor2.execute("PRAGMA table_info(approval_requests)")
    cols = [r[1] for r in cursor2.fetchall()]
    conn2.close()

    assert "idempotency_key" in cols
    assert "execution_status" in cols

def test_p6_6_foreign_key_consistency_check(temp_agent_env):
    """P6 Item 6: Verifies foreign-key-like consistency checks between tool_calls and tool_results."""
    agent_dir, db_file = temp_agent_env
    res_clean = check_tool_call_consistency(db_file)
    assert res_clean["consistent"] is True

    # Insert orphan tool_result
    conn = get_connection(db_file)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO tool_results (id, tool_call_id, session_id, tool_name, result_content) VALUES ('res_orphan', 'nonexistent_call_id', 'sess', 'tool', 'res')"
    )
    conn.commit()
    conn.close()

    res_orphan = check_tool_call_consistency(db_file)
    assert res_orphan["consistent"] is False
    assert res_orphan["orphan_results_count"] >= 1

def test_p6_7_data_inspector_includes_all_safety_tables(temp_agent_env):
    """P6 Item 7: Verifies audit_logs, tool_calls, and tool_results appear in Data Inspector."""
    tables_resp = client.get("/api/data/tables")
    assert tables_resp.status_code == 200
    tables = tables_resp.json().get("tables", [])

    assert "audit_logs" in tables
    assert "tool_calls" in tables
    assert "tool_results" in tables

    for tbl in ["audit_logs", "tool_calls", "tool_results"]:
        r = client.get(f"/api/data/table/{tbl}")
        assert r.status_code == 200
        assert r.json()["table"] == tbl
