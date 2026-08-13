import sqlite3

import pytest

from src.db import init_db
from src.memory.episode_store import StructuredEpisodeRepository, StructuredEpisodeWrite
from src.memory.retrieval_sources import retrieve_structured_episodes
from src.memory.retrieval_types import RetrievalRequest


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "phase9a_episodes.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file


def _episode(**overrides):
    data = {
        "id": "episode-1",
        "session_id": "session-a",
        "title": "Staging deploy review",
        "summary": "The team reviewed staging deployment rollback steps.",
        "participants": ["User", "Assistant"],
        "goals": ["Deploy safely"],
        "decisions": ["Run smoke tests after deploy"],
        "artifacts": ["deploy-checklist.md"],
        "topics": ["deployment", "staging"],
        "importance": 0.8,
        "start_message_id": "turn-1",
        "end_message_id": "turn-4",
        "source": "test",
        "action": "CREATE",
        "source_job_id": "episode-job-1",
    }
    data.update(overrides)
    return StructuredEpisodeWrite(**data)


def _count(db_path, table):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def test_episodic_retrieval_reads_structured_episodes_with_provenance(temp_db):
    repo = StructuredEpisodeRepository(db_path=temp_db)
    repo.append_episode(_episode())
    repo.append_episode(_episode(id="episode-2", session_id="session-b", source_job_id="episode-job-2"))
    before = _count(temp_db, "structured_episodes")

    result = retrieve_structured_episodes(
        RetrievalRequest(query="rollback staging", session_id="session-a", per_source_limit=3),
        db_path=temp_db,
    )

    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.memory_kind == "episodic"
    assert candidate.title == "Staging deploy review"
    assert "Run smoke tests" in candidate.content
    assert candidate.provenance.table_name == "structured_episodes"
    assert candidate.provenance.metadata["action"] == "CREATE"
    assert candidate.provenance.metadata["topics"] == ["deployment", "staging"]
    assert candidate.provenance.metadata["start_message_id"] == "turn-1"
    assert candidate.provenance.metadata["end_message_id"] == "turn-4"
    assert _count(temp_db, "structured_episodes") == before


def test_episodic_retrieval_does_not_change_legacy_episode_search(temp_db):
    repo = StructuredEpisodeRepository(db_path=temp_db)
    repo.append_episode(_episode())

    result = retrieve_structured_episodes(RetrievalRequest(query="staging", session_id="session-a"), db_path=temp_db)

    assert result.candidates
    assert _count(temp_db, "episodes") == 0


def test_episodic_retrieval_falls_back_across_sessions_when_local_empty(temp_db):
    repo = StructuredEpisodeRepository(db_path=temp_db)
    repo.append_episode(_episode())

    result = retrieve_structured_episodes(
        RetrievalRequest(query="rollback staging", session_id="brand_new_session", per_source_limit=3),
        db_path=temp_db,
    )

    assert len(result.candidates) == 1
    assert result.candidates[0].title == "Staging deploy review"
