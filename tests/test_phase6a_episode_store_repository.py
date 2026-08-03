import json
import sqlite3

import pytest

from src.db import init_db
from src.memory.episode_store import (
    StructuredEpisodeRepository,
    StructuredEpisodeWrite,
    build_structured_episode_search_text,
)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "phase6a_repository.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file


def _episode(**overrides):
    data = {
        "id": "episode-1",
        "session_id": "session-1",
        "title": "Designed HITL architecture",
        "summary": "Implemented deterministic approval boundaries.",
        "participants": [" User ", "Assistant", " "],
        "goals": ["Implement approval system"],
        "decisions": ["Use deterministic policy checks"],
        "artifacts": ["policy.yaml"],
        "topics": ["LangGraph", "HITL"],
        "importance": 0.92,
        "start_message_id": "turn-1",
        "end_message_id": "turn-3",
        "source": "phase6a.test",
        "source_job_id": "job-episode-1",
    }
    data.update(overrides)
    return StructuredEpisodeWrite(**data)


def test_append_get_list_and_count_structured_episodes(temp_db):
    repository = StructuredEpisodeRepository(db_path=temp_db)

    record = repository.append_episode(_episode())

    assert record.id == "episode-1"
    assert record.session_id == "session-1"
    assert record.participants == ["User", "Assistant"]
    assert record.topics == ["LangGraph", "HITL"]
    assert record.importance == 0.92
    assert record.created_at
    assert record.updated_at is None

    assert repository.get_by_id("episode-1") == record
    assert repository.get_by_source_job_id("job-episode-1") == record
    assert repository.list_by_session("session-1") == [record]
    assert repository.count_by_session("session-1") == 1
    assert repository.count_by_session("other-session") == 0


def test_list_by_session_order_and_limit(temp_db):
    repository = StructuredEpisodeRepository(db_path=temp_db)
    first = repository.append_episode(_episode(id="episode-a", title="A", source_job_id="job-a"))
    second = repository.append_episode(_episode(id="episode-b", title="B", source_job_id="job-b"))

    assert repository.list_by_session("session-1", limit=1) == [first]
    assert repository.list_by_session("session-1", newest_first=True, limit=1) == [second]

    with pytest.raises(ValueError):
        repository.list_by_session("session-1", limit=0)


def test_source_job_id_idempotency_reuses_existing_row(temp_db):
    repository = StructuredEpisodeRepository(db_path=temp_db)

    first = repository.append_episode(_episode(id="episode-original", source_job_id="job-same"))
    second = repository.append_episode(
        _episode(id="episode-duplicate", title="Different title", source_job_id="job-same")
    )

    assert second == first
    assert repository.count_by_session("session-1") == 1


def test_canonical_json_fields_are_stored_as_text_and_decodable(temp_db):
    repository = StructuredEpisodeRepository(db_path=temp_db)
    repository.append_episode(_episode())

    conn = sqlite3.connect(temp_db)
    try:
        row = conn.execute(
            """
            SELECT participants_json, goals_json, decisions_json, artifacts_json, topics_json
            FROM structured_episodes
            WHERE id = ?
            """,
            ("episode-1",),
        ).fetchone()
    finally:
        conn.close()

    assert row[0] == '["User","Assistant"]'
    assert json.loads(row[1]) == ["Implement approval system"]
    assert json.loads(row[2]) == ["Use deterministic policy checks"]
    assert json.loads(row[3]) == ["policy.yaml"]
    assert json.loads(row[4]) == ["LangGraph", "HITL"]


def test_generated_search_text_is_deterministic_and_has_no_llm_dependency(temp_db):
    episode = _episode(search_text=None)
    expected = build_structured_episode_search_text(episode)
    repository = StructuredEpisodeRepository(db_path=temp_db)

    record = repository.append_episode(episode)

    assert record.search_text == expected
    assert "Title: Designed HITL architecture" in record.search_text
    assert "Goals: Implement approval system" in record.search_text
    assert "Topics: LangGraph, HITL" in record.search_text
    assert "Source: phase6a.test" in record.search_text


def test_search_text_query_behavior(temp_db):
    repository = StructuredEpisodeRepository(db_path=temp_db)
    lower = repository.append_episode(_episode(id="episode-low", title="Budget planning", importance=0.2, source_job_id="job-low"))
    higher = repository.append_episode(_episode(id="episode-high", title="Budget review", importance=0.9, source_job_id="job-high"))
    repository.append_episode(_episode(id="episode-other", session_id="session-2", title="Budget outside", source_job_id="job-other"))

    results = repository.search_text("Budget", session_id="session-1")

    assert [record.id for record in results] == [higher.id, lower.id]
    assert repository.search_text("   ") == []

    with pytest.raises(ValueError):
        repository.search_text("Budget", limit=0)


def test_to_legacy_episode_dict_does_not_write_legacy_table(temp_db):
    repository = StructuredEpisodeRepository(db_path=temp_db)
    record = repository.append_episode(_episode())

    legacy = repository.to_legacy_episode_dict(record)

    assert legacy["id"] == "episode-1"
    assert legacy["session_id"] == "session-1"
    assert legacy["content"] == record.search_text
    assert json.loads(legacy["tool_calls"])["title"] == record.title
    assert legacy["outcome"] == "success"

    conn = sqlite3.connect(temp_db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0] == 0
    finally:
        conn.close()

