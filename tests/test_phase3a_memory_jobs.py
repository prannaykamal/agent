import json

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
    sha256_hex,
)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "phase3a_jobs.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file



@pytest.fixture(autouse=True)
def _cognee_enabled(fake_cognee):
    return fake_cognee


def _state(user_text="Remember that I prefer concise plans.", assistant_text="Got it.", should_store=True, memory=None):
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
        "memory_storage_decision": {
            "should_store": should_store,
            "memory": (memory if memory is not None else f"The user said: {user_text}") if should_store else "",
            "source": "jev",
        },
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
    assert spec_one.idempotency_key.startswith("memq:v1:memory_session_write:")
    assert spec_one.job_id.startswith("memjob_memory_session_write_")

    # The key follows the stored memory text, not the assistant's wording.
    assert build_post_turn_memory_job_specs(_state(assistant_text="Different answer."))[0].idempotency_key == spec_one.idempotency_key
    changed = build_post_turn_memory_job_specs(_state(memory="The user prefers detailed plans."))[0]
    assert changed.idempotency_key != spec_one.idempotency_key


def test_post_turn_emits_one_session_write_when_jev_says_store():
    specs = build_post_turn_memory_job_specs(_state(user_text="I prefer tea.", memory="The user prefers tea."))

    assert [spec.job_type for spec in specs] == ["memory_session_write"]
    payload = specs[0].payload
    assert payload["schema_version"] == 1
    assert payload["source"] == "graph.post_turn"
    assert payload["session_id"] == "phase3a-session"
    assert payload["user_id"] == "default_user"
    # Only Jev's distilled memory is stored, never the transcript.
    assert payload["text"] == "The user prefers tea."


def test_post_turn_emits_nothing_when_jev_says_do_not_store():
    assert build_post_turn_memory_job_specs(_state(should_store=False)) == []
    assert build_post_turn_memory_job_specs({**_state(), "memory_storage_decision": None}) == []


def test_assistant_suggestions_never_reach_the_stored_text():
    state = _state(
        user_text="I love to eat pizza.",
        assistant_text="Try Jamie's Pizzeria or PizzaExpress at Elante Mall!",
        memory="The user loves pizza.",
    )

    [spec] = build_post_turn_memory_job_specs(state)

    assert spec.payload["text"] == "The user loves pizza."
    assert "Elante" not in spec.payload["text"] and "Assistant:" not in spec.payload["text"]


def test_should_store_without_memory_text_stores_nothing():
    assert build_post_turn_memory_job_specs(_state(memory="  ")) == []


def test_offline_fallback_replies_are_never_stored():
    offline = _state(
        user_text="I love to eat pizza.",
        assistant_text="[Gemini/gemini-3.8-flash Primary LLM (Offline)]: Processed request -> 'I love to eat pizza.'\n\nModel call failed: 429",
    )

    assert build_post_turn_memory_job_specs(offline) == []


def test_hitl_pause_and_rejected_turns_are_not_ingested():
    paused = _state(assistant_text="[HUMAN APPROVAL REQUIRED] email_send")
    rejected = {**_state(), "approval_status": "REJECTED"}

    assert build_post_turn_memory_job_specs(paused) == []
    assert build_post_turn_memory_job_specs(rejected) == []


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
    assert row["job_type"] == "memory_session_write"
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
    idempotency_key = "memq:v1:cognee_ingest:test:bad"
    spec = MemoryJobSpec(
        job_type="cognee_ingest",
        payload=bad_payload,
        idempotency_key=idempotency_key,
        job_id=make_memory_job_id("cognee_ingest", idempotency_key),
        session_id="phase3a-session",
    )

    with pytest.raises(TypeError):
        repo.enqueue(spec)

    assert repo.count_by_session("phase3a-session") == 0


def test_sha256_helper_returns_hex_digest():
    digest = sha256_hex("phase3a")

    assert len(digest) == 64
    int(digest, 16)


