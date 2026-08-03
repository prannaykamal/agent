import json
import sqlite3
from types import SimpleNamespace

import pytest

from src.db import init_db
from src.harness.llm_router import LLMRouteResult, LLMSelector
from src.memory.job_handlers import EpisodeGenerationJobHandler


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "phase8b_episode_enqueue.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file


def _insert_turn(db_path, turn_id, sender, content):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO raw_turns (id, session_id, sender, content, tokens, created_at) VALUES (?, ?, ?, ?, ?, datetime('now'))",
            (turn_id, "sess", sender, content, 10),
        )
        conn.commit()
    finally:
        conn.close()


class FakeLLM:
    def invoke(self, prompt):
        return SimpleNamespace(
            content=json.dumps(
                {
                    "title": "Deploy Staging",
                    "summary": "The user completed a staging deployment workflow.",
                    "participants": ["User", "Assistant"],
                    "goals": ["Deploy staging"],
                    "decisions": ["Run smoke checks"],
                    "artifacts": ["deploy script"],
                    "topics": ["deploy", "staging"],
                    "importance": 0.8,
                }
            )
        )


def _route():
    return LLMRouteResult(
        selector=LLMSelector("secondary", "openai", "gpt-4o-mini", 0.3, 128000, "test"),
        llm=FakeLLM(),
        available=True,
        fallback_used=False,
    )


def _payload():
    return {
        "schema_version": 1,
        "source": "graph.episode_detector",
        "session_id": "sess",
        "models": {
            "primary_provider": "openai",
            "primary_model_name": "gpt-4o-mini",
            "secondary_provider": "openai",
            "secondary_model_name": "gpt-4o-mini",
        },
        "episodic": {
            "schema_version": 1,
            "trigger_reason": "explicit_memory_request",
            "trigger_reasons": ["explicit_memory_request"],
            "source_window": {
                "turn_ids": ["t1", "t2"],
                "start_message_id": "t1",
                "end_message_id": "t2",
                "token_count": 20,
                "source_text_mode": "raw_turns",
                "summary_block_ids": [],
                "user_text_hash": "u",
                "assistant_text_hash": "a",
            },
            "continuation": {
                "action": "CREATE",
                "parent_episode_id": None,
                "related_episode_ids": [],
                "score": 0.8,
                "rationale_code": "test",
            },
        },
    }


def _memory_jobs(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in conn.execute("SELECT * FROM memory_jobs ORDER BY created_at ASC").fetchall()]
    finally:
        conn.close()


def test_episode_generation_enqueues_procedural_candidate_generation(temp_db, monkeypatch):
    _insert_turn(temp_db, "t1", "user", "Deploy staging")
    _insert_turn(temp_db, "t2", "assistant", "Done")
    monkeypatch.setattr("src.memory.job_handlers._resolve_secondary_route", lambda payload: _route())

    result = EpisodeGenerationJobHandler().handle({"id": "job-episode", "session_id": "sess"}, _payload())

    jobs = _memory_jobs(temp_db)
    assert result.success is True
    assert result.result["procedural_candidate_job_inserted"] is True
    assert len(jobs) == 1
    assert jobs[0]["job_type"] == "procedural_candidate_generation"


def test_duplicate_episode_processing_reuses_existing_procedural_job(temp_db, monkeypatch):
    _insert_turn(temp_db, "t1", "user", "Deploy staging")
    _insert_turn(temp_db, "t2", "assistant", "Done")
    monkeypatch.setattr("src.memory.job_handlers._resolve_secondary_route", lambda payload: _route())
    handler = EpisodeGenerationJobHandler()

    first = handler.handle({"id": "job-episode", "session_id": "sess"}, _payload())
    second = handler.handle({"id": "job-episode", "session_id": "sess"}, _payload())

    assert first.result["procedural_candidate_job_id"] == second.result["procedural_candidate_job_id"]
    assert second.result["procedural_candidate_job_inserted"] is False
    assert len(_memory_jobs(temp_db)) == 1


def test_procedural_enqueue_failure_does_not_fail_episode_generation(temp_db, monkeypatch):
    _insert_turn(temp_db, "t1", "user", "Deploy staging")
    _insert_turn(temp_db, "t2", "assistant", "Done")
    monkeypatch.setattr("src.memory.job_handlers._resolve_secondary_route", lambda payload: _route())

    def fail_enqueue(*args, **kwargs):
        raise RuntimeError("queue unavailable")

    monkeypatch.setattr("src.memory.jobs.enqueue_procedural_candidate_generation_job", fail_enqueue)

    result = EpisodeGenerationJobHandler().handle({"id": "job-episode", "session_id": "sess"}, _payload())

    assert result.success is True
    assert result.result["procedural_candidate_enqueue_failed"] is True
    assert len(_memory_jobs(temp_db)) == 0
