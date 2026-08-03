import json
import sqlite3

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.db import init_db
from src.memory.job_repository import MemoryJobRepository
from src.memory.jobs import (
    MEMORY_JOB_STATUS_QUEUED,
    MemoryJobSpec,
    build_post_turn_memory_job_specs,
    canonical_json,
    make_memory_job_id,
    make_post_turn_idempotency_key,
    sha256_hex,
)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "phase3a_jobs.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file



def _insert_turn(db_path, turn_id, sender, content, tokens=10):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO raw_turns (id, session_id, sender, content, tokens, created_at) VALUES (?, ?, ?, ?, ?, datetime('now'))",
            (turn_id, "phase3a-session", sender, content, tokens),
        )
        conn.commit()
    finally:
        conn.close()

def _state(user_text="Remember that I prefer concise plans.", assistant_text="Got it."):
    return {
        "messages": [HumanMessage(content=user_text), AIMessage(content=assistant_text)],
        "session_id": "phase3a-session",
        "provider": "openai",
        "model_name": "gpt-4o-mini",
        "secondary_provider": "anthropic",
        "secondary_model_name": "claude-3-5-haiku",
        "retrieval_triggered": False,
        "tools_used": [],
        "loop_count": 1,
        "approval_status": "NONE",
        "token_count": 17,
    }


def test_canonical_json_is_deterministic_and_decodable():
    left = {"b": 2, "a": {"d": 4, "c": 3}}
    right = {"a": {"c": 3, "d": 4}, "b": 2}

    encoded = canonical_json(left)

    assert encoded == canonical_json(right)
    assert json.loads(encoded) == right


def test_job_id_and_idempotency_key_are_deterministic():
    spec_one = build_post_turn_memory_job_specs(_state())[0]
    spec_two = build_post_turn_memory_job_specs(_state())[0]

    assert spec_one.idempotency_key == spec_two.idempotency_key
    assert spec_one.job_id == spec_two.job_id
    assert spec_one.idempotency_key.startswith("memq:v1:semantic_candidate_extraction:")
    assert spec_one.job_id.startswith("memjob_semantic_candidate_extraction_")

    changed = build_post_turn_memory_job_specs(_state(assistant_text="Different answer."))[0]
    assert changed.idempotency_key != spec_one.idempotency_key


def test_post_turn_job_spec_builder_only_emits_allowed_phase3a_jobs():
    specs = build_post_turn_memory_job_specs(_state(user_text="Hello there."))

    assert [spec.job_type for spec in specs] == ["semantic_candidate_extraction"]
    payload = specs[0].payload
    assert payload["schema_version"] == 1
    assert payload["source"] == "graph.post_turn"
    assert payload["session_id"] == "phase3a-session"
    assert payload["turn"]["user_text"] == "Hello there."
    assert payload["turn"]["assistant_text"] == "Got it."
    assert payload["models"]["primary_provider"] == "openai"
    assert payload["models"]["secondary_provider"] == "anthropic"
    assert payload["semantic"]["candidate_source"] == "post_turn"

    forbidden = {
        "procedural_candidate_generation",
        "semantic_consolidation",
        "procedural_consolidation",
        "skill_promotion",
        "summary_generation",
    }
    assert forbidden.isdisjoint({spec.job_type for spec in specs})


def test_episode_generation_only_when_deterministic_trigger_exists(temp_db):
    _insert_turn(temp_db, "t1", "user", "Please remember that I like short reports.")
    _insert_turn(temp_db, "t2", "assistant", "Got it.")
    specs = build_post_turn_memory_job_specs(_state(user_text="Please remember that I like short reports."))

    assert [spec.job_type for spec in specs] == [
        "semantic_candidate_extraction",
        "episode_generation",
    ]
    episode_payload = specs[1].payload
    assert episode_payload["episodic"]["trigger_reason"] == "explicit_memory_request"


def test_repository_enqueue_inserts_queued_job(temp_db):
    spec = build_post_turn_memory_job_specs(_state())[0]
    repo = MemoryJobRepository(db_path=temp_db)

    result = repo.enqueue(spec, max_attempts=5)
    row = repo.get_by_idempotency_key(spec.idempotency_key)

    assert result.inserted is True
    assert result.job_id == spec.job_id
    assert row is not None
    assert row["status"] == MEMORY_JOB_STATUS_QUEUED
    assert row["attempt_count"] == 0
    assert row["max_attempts"] == 5
    assert row["job_type"] == "semantic_candidate_extraction"
    assert json.loads(row["payload_json"]) == spec.payload


def test_duplicate_idempotency_key_does_not_duplicate_rows(temp_db):
    spec = build_post_turn_memory_job_specs(_state())[0]
    repo = MemoryJobRepository(db_path=temp_db)

    first = repo.enqueue(spec)
    second = repo.enqueue(spec)

    assert first.inserted is True
    assert second.inserted is False
    assert second.job_id == first.job_id
    assert repo.count_by_session("phase3a-session") == 1


def test_repository_rejects_non_json_payload_before_insert(temp_db):
    repo = MemoryJobRepository(db_path=temp_db)
    bad_payload = {"session_id": "phase3a-session", "bad": object()}
    idempotency_key = make_post_turn_idempotency_key(
        "semantic_candidate_extraction",
        {"session_id": "phase3a-session", "turn": {}, "models": {}},
    )
    spec = MemoryJobSpec(
        job_type="semantic_candidate_extraction",
        payload=bad_payload,
        idempotency_key=idempotency_key,
        job_id=make_memory_job_id("semantic_candidate_extraction", idempotency_key),
        session_id="phase3a-session",
    )

    with pytest.raises(TypeError):
        repo.enqueue(spec)

    assert repo.count_by_session("phase3a-session") == 0


def test_sha256_helper_returns_hex_digest():
    digest = sha256_hex("phase3a")

    assert len(digest) == 64
    int(digest, 16)


