import json
import sqlite3

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.db import init_db
from src.memory.job_repository import MemoryJobRepository
from src.memory.jobs import (
    build_post_turn_memory_job_specs,
    enqueue_post_turn_memory_jobs,
    make_episode_generation_idempotency_key,
)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "phase6b_jobs.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file


def _insert_turn(db_path, turn_id, sender, content, tokens=10, created_at="2026-08-03 10:00:00"):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO raw_turns (id, session_id, sender, content, tokens, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (turn_id, "sess", sender, content, tokens, created_at),
        )
        conn.commit()
    finally:
        conn.close()


def _state(user="Please remember that deploys need approval", assistant="Got it", **overrides):
    state = {
        "messages": [HumanMessage(content=user), AIMessage(content=assistant)],
        "session_id": "sess",
        "provider": "openai",
        "model_name": "gpt-4o-mini",
        "secondary_provider": "anthropic",
        "secondary_model_name": "claude-3-5-haiku",
        "retrieval_triggered": False,
        "tools_used": [],
        "loop_count": 1,
        "approval_status": "NONE",
        "token_count": 20,
    }
    state.update(overrides)
    return state


def test_episode_payload_shape_for_explicit_remember(temp_db):
    _insert_turn(temp_db, "t1", "user", "Please remember that deploys need approval")
    _insert_turn(temp_db, "t2", "assistant", "Got it")

    specs = build_post_turn_memory_job_specs(_state())
    episode = next(spec for spec in specs if spec.job_type == "episode_generation")

    assert [spec.job_type for spec in specs] == ["semantic_candidate_extraction", "episode_generation"]
    assert episode.priority == 60
    payload = episode.payload
    assert payload["source"] == "graph.episode_detector"
    assert payload["episodic"]["schema_version"] == 1
    assert payload["episodic"]["trigger_reason"] == "explicit_memory_request"
    assert payload["episodic"]["trigger_reasons"] == ["explicit_memory_request"]
    assert payload["episodic"]["source_window"]["turn_ids"] == ["t1", "t2"]
    assert payload["episodic"]["continuation"]["action"] == "CREATE"
    assert payload["models"]["secondary_provider"] == "anthropic"


def test_ordinary_turn_still_enqueues_only_semantic(temp_db):
    _insert_turn(temp_db, "t1", "user", "Hello")
    _insert_turn(temp_db, "t2", "assistant", "Hi")

    specs = build_post_turn_memory_job_specs(_state(user="Hello", assistant="Hi"))

    assert [spec.job_type for spec in specs] == ["semantic_candidate_extraction"]


def test_episode_idempotency_key_is_deterministic():
    first = make_episode_generation_idempotency_key(
        session_id="sess",
        turn_ids=["t1", "t2"],
        trigger_reasons=["explicit_memory_request"],
        action="CREATE",
        parent_episode_id=None,
        secondary_provider="openai",
        secondary_model_name="gpt-4o-mini",
    )
    second = make_episode_generation_idempotency_key(
        session_id="sess",
        turn_ids=["t1", "t2"],
        trigger_reasons=["explicit_memory_request"],
        action="CREATE",
        parent_episode_id=None,
        secondary_provider="openai",
        secondary_model_name="gpt-4o-mini",
    )

    assert first == second
    assert first.startswith("memq:v1:episode_generation:")


def test_duplicate_enqueue_reuses_existing_memory_job(temp_db):
    _insert_turn(temp_db, "t1", "user", "Please remember that deploys need approval")
    _insert_turn(temp_db, "t2", "assistant", "Got it")

    first = enqueue_post_turn_memory_jobs(_state())
    second = enqueue_post_turn_memory_jobs(_state())
    repo = MemoryJobRepository(db_path=temp_db)

    assert [result.inserted for result in first] == [True, True]
    assert [result.inserted for result in second] == [False, False]
    assert repo.count_by_session("sess") == 2


@pytest.mark.parametrize("approval_status", ["PENDING", "REJECTED"])
def test_hitl_pending_and_rejected_enqueue_no_jobs(temp_db, approval_status):
    _insert_turn(temp_db, "t1", "user", "Please remember this")
    _insert_turn(temp_db, "t2", "assistant", "OK")

    assert build_post_turn_memory_job_specs(_state(approval_status=approval_status)) == []


def test_trimming_payload_uses_summary_omitted_turn_ids(temp_db):
    _insert_turn(temp_db, "t1", "user", "old omitted")
    _insert_turn(temp_db, "t2", "assistant", "new kept")

    specs = build_post_turn_memory_job_specs(
        _state(user="Current", assistant="OK", trimming_occurred=True, summary_omitted_turn_ids=["t1"])
    )
    episode = next(spec for spec in specs if spec.job_type == "episode_generation")

    assert episode.payload["trigger_metadata"]["trimming_occurred"] is True
    assert episode.payload["episodic"]["trigger_reason"] == "trimming_occurred"
    assert episode.payload["episodic"]["source_window"]["turn_ids"] == ["t1"]


def test_payload_is_canonical_json_decodable(temp_db):
    _insert_turn(temp_db, "t1", "user", "Please remember this")
    _insert_turn(temp_db, "t2", "assistant", "OK")
    episode = next(spec for spec in build_post_turn_memory_job_specs(_state(user="Please remember this")) if spec.job_type == "episode_generation")

    decoded = json.loads(json.dumps(episode.payload, sort_keys=True))

    assert decoded["episodic"]["continuation"]["action"] == "CREATE"

