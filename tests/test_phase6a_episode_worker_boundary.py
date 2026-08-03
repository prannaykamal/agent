import json
import sqlite3

import pytest

from src.db import init_db
from src.memory.episode_store import StructuredEpisodeRepository, StructuredEpisodeWrite
from src.memory.episodic import log_episode, search_episodes_fts
from src.memory.job_handlers import build_default_handler_registry
from src.memory.job_router import MemoryJobRouter


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "phase6a_worker_boundary.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file


def _structured_episode():
    return StructuredEpisodeWrite(
        id="structured-episode-1",
        session_id="session-1",
        title="Structured storage design",
        summary="Added repository-only storage for structured episodes.",
        participants=["User", "Assistant"],
        goals=["Keep episode generation inert"],
        decisions=["Use repository boundary"],
        artifacts=["src/memory/episode_store.py"],
        topics=["Episodic memory"],
        importance=0.7,
        start_message_id="turn-1",
        end_message_id="turn-2",
        source="phase6a.test",
        source_job_id="job-structured-1",
    )


def _counts(db_path):
    tables = [
        "episodes",
        "structured_episodes",
        "raw_turns",
        "facts",
        "pending_fact_candidates",
        "summary_blocks",
        "semantic_embeddings",
        "skill_candidates",
        "skill_versions",
    ]
    conn = sqlite3.connect(db_path)
    try:
        return {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables}
    finally:
        conn.close()


def test_legacy_episodes_are_unaffected_and_fts_still_works(temp_db):
    log_episode("legacy-session", "User asked about project deadlines", outcome="success", db_path=temp_db)

    results = search_episodes_fts("deadlines", db_path=temp_db)

    assert len(results) == 1
    assert results[0]["session_id"] == "legacy-session"
    assert "project deadlines" in results[0]["content"]

    conn = sqlite3.connect(temp_db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM structured_episodes").fetchone()[0] == 0
    finally:
        conn.close()


def test_structured_writes_do_not_appear_in_legacy_episode_search(temp_db):
    repository = StructuredEpisodeRepository(db_path=temp_db)
    repository.append_episode(_structured_episode())

    assert search_episodes_fts("Structured", db_path=temp_db) == []

    conn = sqlite3.connect(temp_db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM structured_episodes").fetchone()[0] == 1
    finally:
        conn.close()


def test_episode_generation_handler_is_real_after_phase6b_but_rejects_minimal_payload():
    registry = build_default_handler_registry()

    handler = registry["episode_generation"]
    result = handler.handle(
        job={"id": "job-episode-generation", "job_type": "episode_generation"},
        payload={"schema_version": 1},
    )

    assert handler.__class__.__name__ == "EpisodeGenerationJobHandler"
    assert result.success is False
    assert result.retryable is False
    assert result.result["processed"] is False


def test_old_episode_generation_payload_does_not_call_secondary_llm_or_write_tables(temp_db, monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("secondary LLM route should not be used by episode_generation in Phase 6A")

    monkeypatch.setattr("src.harness.models.get_secondary_llm", fail)
    monkeypatch.setattr("src.harness.llm_router.resolve_secondary_llm", fail)
    monkeypatch.setattr("src.harness.llm_router.resolve_secondary_from_job_payload", fail)

    before = _counts(temp_db)
    router = MemoryJobRouter()

    result = router.dispatch(
        {
            "id": "job-episode-generation",
            "job_type": "episode_generation",
            "session_id": "session-1",
            "payload_json": json.dumps(
                {
                    "schema_version": 1,
                    "session_id": "session-1",
                    "episodic": {"trigger_reason": "explicit_memory_request"},
                }
            ),
        }
    )

    assert result.success is False
    assert result.retryable is False
    assert result.result["processed"] is False
    assert _counts(temp_db) == before


def test_summary_generation_handler_remains_phase5b_real_handler():
    registry = build_default_handler_registry()

    assert registry["summary_generation"].__class__.__name__ == "SummaryGenerationJobHandler"




