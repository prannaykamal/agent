import pytest
import zipfile
from pathlib import Path
from fastapi.testclient import TestClient
from src.db import init_db, get_connection
from src.db_migrations import run_db_migrations
from src.startup import ensure_system_initialized
from src.background_worker import process_due_scheduled_jobs
from src.personal_os.backup import export_agent_backup
from src.api.server import app

@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_reliability.db"
    mem_file = tmp_path / "MEMORY.md"

    monkeypatch.setattr("src.db.DB_PATH", db_file)
    monkeypatch.setattr("src.config.MEMORY_PATH", mem_file)
    init_db(db_file)
    return db_file

client = TestClient(app)

def test_db_migrations(temp_db):
    run_db_migrations(temp_db)
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT version, description FROM schema_migrations ORDER BY version DESC LIMIT 1")
    row = cursor.fetchone()
    conn.close()

    assert row is not None
    assert row["version"] >= 4

def test_ensure_system_initialized(temp_db, tmp_path, monkeypatch):
    test_agent_dir = tmp_path / ".test_agent"
    monkeypatch.setattr("src.startup.AGENT_DIR", test_agent_dir)
    monkeypatch.setattr("src.startup.SOUL_PATH", test_agent_dir / "SOUL.md")
    monkeypatch.setattr("src.startup.DB_PATH", test_agent_dir / "state.db")

    res = ensure_system_initialized()
    assert res["status"] == "INITIALIZED"
    assert (test_agent_dir / "SOUL.md").exists()
    assert (test_agent_dir / "cognee").is_dir()

def test_background_worker_scheduled_jobs(temp_db):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO scheduled_jobs (id, cron_or_timestamp, task_payload, status)
        VALUES ('job_rel_1', '2026-01-01 00:00', 'run health check', 'PENDING')
        """
    )
    conn.commit()
    conn.close()

    processed = process_due_scheduled_jobs(temp_db)
    assert len(processed) == 1
    assert processed[0]["id"] == "job_rel_1"
    assert processed[0]["status"] == "COMPLETED"


def test_export_agent_backup(temp_db, tmp_path, monkeypatch):
    out_dir = tmp_path / "backups"
    monkeypatch.setattr("src.personal_os.backup.DB_PATH", temp_db)
    
    res = export_agent_backup(out_dir)
    assert res["status"] == "SUCCESS"
    assert Path(res["backup_path"]).exists()

    with zipfile.ZipFile(res["backup_path"], "r") as zf:
        namelist = zf.namelist()
        assert "state.db" in namelist

def test_api_backup_endpoint(temp_db):
    resp = client.post("/api/system/backup")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "SUCCESS"
