from datetime import datetime

import pytest

from src.db import init_db
from src.memory.consolidation_scheduler import maybe_enqueue_idle_semantic_consolidation
from src.memory.episode_store import StructuredEpisodeRepository, StructuredEpisodeWrite
from src.memory.worker import process_one_memory_job


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "consolidation_scheduler.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file


def _episode(index: int) -> StructuredEpisodeWrite:
    return StructuredEpisodeWrite(
        id=f"episode-{index}",
        session_id="sess",
        title=f"Episode {index}",
        summary="A structured work episode.",
        participants=["User"],
        goals=["Build memory"],
        decisions=[],
        artifacts=[],
        topics=["memory"],
        importance=0.6,
        start_message_id=f"turn-{index}",
        end_message_id=f"turn-{index}",
        source="test",
        source_job_id=f"job-episode-{index}",
    )


def _consolidation_jobs(db_path):
    import sqlite3

    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM memory_jobs WHERE job_type = 'semantic_consolidation'"
        ).fetchone()[0]
    finally:
        conn.close()


def test_idle_scheduler_enqueues_when_episode_threshold_met(temp_db):
    repository = StructuredEpisodeRepository(db_path=temp_db)
    for index in range(10):
        repository.append_episode(_episode(index))

    created = maybe_enqueue_idle_semantic_consolidation(
        db_path=temp_db,
        now=datetime(2026, 1, 2, 12, 0, 0),
    )

    assert created >= 1
    assert _consolidation_jobs(temp_db) >= 1


def test_idle_worker_enqueues_consolidation_without_graph(temp_db):
    repository = StructuredEpisodeRepository(db_path=temp_db)
    for index in range(10):
        repository.append_episode(_episode(index))

    result = process_one_memory_job(
        worker_id="worker-idle",
        db_path=temp_db,
        now=datetime(2026, 1, 2, 12, 0, 0),
    )

    assert result.status == "IDLE"
    assert _consolidation_jobs(temp_db) >= 1


def test_scheduler_is_idempotent_for_the_same_window(temp_db):
    repository = StructuredEpisodeRepository(db_path=temp_db)
    for index in range(10):
        repository.append_episode(_episode(index))
    now = datetime(2026, 1, 2, 12, 0, 0)

    maybe_enqueue_idle_semantic_consolidation(db_path=temp_db, now=now)
    first = _consolidation_jobs(temp_db)
    maybe_enqueue_idle_semantic_consolidation(db_path=temp_db, now=now)
    second = _consolidation_jobs(temp_db)

    assert first >= 1
    assert second == first


def _job_trigger_types(db_path):
    import json
    import sqlite3

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT payload_json FROM memory_jobs WHERE job_type = 'semantic_consolidation'").fetchall()
        types = []
        for row in rows:
            payload = json.loads(row[0])
            types.append(payload.get("semantic_consolidation", {}).get("trigger_type"))
        return types
    finally:
        conn.close()


def test_daily_idle_does_not_enqueue_twice_inside_the_interval(temp_db):
    repository = StructuredEpisodeRepository(db_path=temp_db)
    repository.append_episode(_episode(0))

    first = maybe_enqueue_idle_semantic_consolidation(
        db_path=temp_db,
        now=datetime(2026, 1, 2, 23, 0, 0),
        worker_id="worker-interval",
    )
    second = maybe_enqueue_idle_semantic_consolidation(
        db_path=temp_db,
        now=datetime(2026, 1, 3, 0, 1, 0),
        worker_id="worker-interval",
    )
    types = _job_trigger_types(temp_db)

    assert first >= 1
    assert second == 0
    assert types.count("daily_idle") == 1


def test_episode_threshold_still_enqueues_when_daily_is_inside_interval(temp_db):
    repository = StructuredEpisodeRepository(db_path=temp_db)
    repository.append_episode(_episode(0))
    maybe_enqueue_idle_semantic_consolidation(
        db_path=temp_db,
        now=datetime(2026, 1, 2, 12, 0, 0),
        worker_id="worker-threshold",
    )
    for index in range(1, 10):
        repository.append_episode(_episode(index))

    created = maybe_enqueue_idle_semantic_consolidation(
        db_path=temp_db,
        now=datetime(2026, 1, 2, 12, 0, 5),
        worker_id="worker-threshold",
    )
    types = _job_trigger_types(temp_db)

    assert created >= 1
    assert "structured_episode_threshold" in types
    assert types.count("daily_idle") == 1
