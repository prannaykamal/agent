import json
import sqlite3
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.db import init_db
from src.harness.llm_router import LLMRouteResult, LLMSelector
from src.memory.episode_continuation import decide_episode_continuation
from src.memory.episodic import log_episode, search_episodes_fts
from src.memory.episode_detector import detect_episode_trigger
from src.memory.episode_store import StructuredEpisodeRecord, StructuredEpisodeRepository
from src.memory.job_handlers import EpisodeGenerationJobHandler
from src.memory.summary_blocks import RawTurnRecord


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "phase11_episodic.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file


class FakeLLM:
    def __init__(self, content):
        self.content = content
        self.calls = []

    def invoke(self, prompt):
        self.calls.append(prompt)
        return SimpleNamespace(content=self.content)


def _route(llm=None, available=True):
    return LLMRouteResult(
        selector=LLMSelector("secondary", "openai", "gpt-4o-mini", 0.3, 128000, "test"),
        llm=llm,
        available=available,
        fallback_used=False,
        error=None if available else "unavailable",
    )


def _turn(turn_id, sender, content, tokens=10):
    return RawTurnRecord(turn_id, "phase11-episodic", sender, content, tokens, "2026-01-01 12:00:00")


def _insert_turn(db_path, turn_id, sender, content):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO raw_turns (id, session_id, sender, content, tokens, created_at) VALUES (?, ?, ?, ?, ?, datetime('now'))",
            (turn_id, "phase11-episodic", sender, content, 10),
        )
        conn.commit()
    finally:
        conn.close()


def _count(db_path, table):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def _episode_json():
    return json.dumps(
        {
            "title": "Deployment approval",
            "summary": "The user asked to remember deployment approval rules.",
            "participants": ["User", "Assistant"],
            "goals": ["Deploy safely"],
            "decisions": ["Require approval"],
            "artifacts": ["deploy.md"],
            "topics": ["deployment", "approval"],
            "importance": 0.9,
            "action": "MERGE",
            "parent_episode_id": "llm-parent",
        }
    )


def _payload(action="CREATE", parent=None):
    return {
        "schema_version": 1,
        "session_id": "phase11-episodic",
        "models": {"secondary_provider": "openai", "secondary_model_name": "gpt-4o-mini"},
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
                "action": action,
                "parent_episode_id": parent,
                "related_episode_ids": [parent] if parent else [],
                "score": 0.8,
                "rationale_code": "phase11",
            },
        },
    }


def test_deterministic_trigger_and_continuation_do_not_call_llms(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("detector and continuation must not use LLMs")

    monkeypatch.setattr("src.harness.llm_router.resolve_secondary_llm", fail)
    raw_turns = [
        _turn("t1", "user", "Please remember deployment approval"),
        _turn("t2", "assistant", "OK"),
    ]
    detection = detect_episode_trigger(
        state={"session_id": "phase11-episodic", "messages": [HumanMessage(content="Please remember deployment approval"), AIMessage(content="OK")]},
        raw_turns=raw_turns,
        existing_episodes=[],
    )
    continuation = decide_episode_continuation(source_window=detection.source_window, raw_turns=raw_turns, existing_episodes=[])

    assert detection.should_enqueue is True
    assert detection.primary_reason == "explicit_memory_request"
    assert continuation.action == "CREATE"


def test_episode_generation_worker_only_secondary_and_idempotent_structured_write(temp_db, monkeypatch):
    _insert_turn(temp_db, "t1", "user", "Please remember deployment approval")
    _insert_turn(temp_db, "t2", "assistant", "OK")
    llm = FakeLLM(_episode_json())
    monkeypatch.setattr("src.memory.job_handlers._resolve_secondary_route", lambda payload: _route(llm))

    handler = EpisodeGenerationJobHandler()
    first = handler.handle({"id": "episode-job", "job_type": "episode_generation", "session_id": "phase11-episodic"}, _payload(action="UPDATE", parent="parent-episode"))
    second = handler.handle({"id": "episode-job", "job_type": "episode_generation", "session_id": "phase11-episodic"}, _payload(action="UPDATE", parent="parent-episode"))
    record = StructuredEpisodeRepository(db_path=temp_db).list_by_session("phase11-episodic")[0]

    assert first.success is True
    assert second.success is True
    assert _count(temp_db, "structured_episodes") == 1
    assert record.action == "UPDATE"
    assert record.parent_episode_id == "parent-episode"
    assert llm.calls


def test_episode_handler_preserves_legacy_episode_search_and_enqueues_procedural_job(temp_db, monkeypatch):
    log_episode("phase11-episodic", "Legacy deployment episode", db_path=temp_db)
    _insert_turn(temp_db, "t1", "user", "Please remember deployment approval")
    _insert_turn(temp_db, "t2", "assistant", "OK")
    monkeypatch.setattr("src.memory.job_handlers._resolve_secondary_route", lambda payload: _route(FakeLLM(_episode_json())))

    result = EpisodeGenerationJobHandler().handle({"id": "episode-job", "job_type": "episode_generation", "session_id": "phase11-episodic"}, _payload())

    assert result.success is True
    assert _count(temp_db, "structured_episodes") == 1
    assert _count(temp_db, "memory_jobs") == 1
    assert search_episodes_fts("deployment", db_path=temp_db)


def test_procedural_enqueue_failure_does_not_fail_episode_generation(temp_db, monkeypatch):
    _insert_turn(temp_db, "t1", "user", "Please remember deployment approval")
    _insert_turn(temp_db, "t2", "assistant", "OK")
    monkeypatch.setattr("src.memory.job_handlers._resolve_secondary_route", lambda payload: _route(FakeLLM(_episode_json())))

    def fail_enqueue(*args, **kwargs):
        raise RuntimeError("queue unavailable")

    monkeypatch.setattr("src.memory.jobs.enqueue_procedural_candidate_generation_job", fail_enqueue)

    result = EpisodeGenerationJobHandler().handle({"id": "episode-job", "job_type": "episode_generation", "session_id": "phase11-episodic"}, _payload())

    assert result.success is True
    assert result.result["procedural_candidate_enqueue_failed"] is True
    assert _count(temp_db, "memory_jobs") == 0



