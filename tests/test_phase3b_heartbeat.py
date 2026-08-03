import json
import sqlite3
from datetime import datetime

import pytest

from src.db import init_db
from src.memory.job_repository import MemoryJobRepository


NOW = datetime(2026, 1, 1, 12, 0, 0)
LATER = datetime(2026, 1, 1, 12, 1, 0)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "phase3b_heartbeat.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file


def _heartbeat(db_path, worker_id):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM worker_heartbeats WHERE worker_id = ?", (worker_id,)).fetchone()
        return dict(row)
    finally:
        conn.close()


def test_heartbeat_insert_and_update(temp_db):
    repo = MemoryJobRepository(db_path=temp_db)

    repo.upsert_worker_heartbeat(
        worker_id="worker-1",
        status="RUNNING",
        current_job_id="job-1",
        metadata={"phase": "3B"},
        now=NOW,
    )
    repo.upsert_worker_heartbeat(
        worker_id="worker-1",
        status="IDLE",
        current_job_id=None,
        metadata={"phase": "3B", "updated": True},
        now=LATER,
    )

    row = _heartbeat(temp_db, "worker-1")
    assert row["worker_type"] == "memory"
    assert row["status"] == "IDLE"
    assert row["current_job_id"] is None
    assert row["last_heartbeat_at"] == "2026-01-01 12:01:00"
    assert json.loads(row["metadata_json"]) == {"phase": "3B", "updated": True}


def test_heartbeat_can_track_current_job_while_running(temp_db):
    repo = MemoryJobRepository(db_path=temp_db)

    repo.upsert_worker_heartbeat(
        worker_id="worker-2",
        status="RUNNING",
        current_job_id="job-active",
        metadata={"phase": "3B"},
        now=NOW,
    )

    row = _heartbeat(temp_db, "worker-2")
    assert row["status"] == "RUNNING"
    assert row["current_job_id"] == "job-active"
