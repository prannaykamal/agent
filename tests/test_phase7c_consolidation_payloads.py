import pytest

from src.db import init_db
from src.memory.job_repository import MemoryJobRepository
from src.memory.jobs import (
    build_semantic_consolidation_job_spec,
    build_semantic_consolidation_payload,
    enqueue_semantic_consolidation_job,
    make_semantic_consolidation_idempotency_key,
)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "phase7c_payloads.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file


def test_semantic_consolidation_job_payload_and_idempotency():
    payload = build_semantic_consolidation_payload(
        session_id="sess",
        trigger_type="pending_candidate_threshold",
        window_key="candidates:sess:1",
        primary_provider="xai",
        primary_model_name="grok-3",
        secondary_provider="unknown-provider",
        secondary_model_name="gpt-4o-mini",
        candidate_ids=["cand-1", "cand-2"],
        episode_ids=["episode-1"],
        maintenance_date=None,
    )

    assert payload["schema_version"] == 1
    assert payload["session_id"] == "sess"
    assert payload["models"]["primary_provider"] == "grok"
    assert payload["models"]["secondary_provider"] == "openai"
    assert payload["semantic_consolidation"]["candidate_ids"] == ["cand-1", "cand-2"]
    assert payload["semantic_consolidation"]["promote_through_dedup_store"] is True

    first_key = make_semantic_consolidation_idempotency_key(
        session_id="sess",
        trigger_type="pending_candidate_threshold",
        window_key="candidates:sess:1",
        candidate_ids=["cand-1", "cand-2"],
        episode_ids=["episode-1"],
        secondary_provider="openai",
        secondary_model_name="gpt-4o-mini",
    )
    second_key = make_semantic_consolidation_idempotency_key(
        session_id="sess",
        trigger_type="pending_candidate_threshold",
        window_key="candidates:sess:1",
        candidate_ids=["cand-1", "cand-2"],
        episode_ids=["episode-1"],
        secondary_provider="openai",
        secondary_model_name="gpt-4o-mini",
    )
    assert first_key == second_key


def test_semantic_consolidation_job_spec_and_duplicate_enqueue_reuses_row(temp_db):
    spec = build_semantic_consolidation_job_spec(
        session_id="sess",
        trigger_type="manual",
        window_key="manual:sess:review",
        primary_provider="openai",
        primary_model_name="gpt-4o-mini",
        secondary_provider="openai",
        secondary_model_name="gpt-4o-mini",
        candidate_ids=["cand-1"],
    )

    assert spec.job_type == "semantic_consolidation"
    assert spec.priority == 70
    assert spec.job_id.startswith("memjob_semantic_consolidation_")

    class Queue:
        def __init__(self):
            self.repository = MemoryJobRepository(db_path=temp_db)

        def enqueue_spec(self, spec):
            return self.repository.enqueue(spec)

    queue = Queue()
    first = enqueue_semantic_consolidation_job(
        session_id="sess",
        trigger_type="manual",
        window_key="manual:sess:review",
        primary_provider="openai",
        primary_model_name="gpt-4o-mini",
        secondary_provider="openai",
        secondary_model_name="gpt-4o-mini",
        candidate_ids=["cand-1"],
        queue=queue,
    )
    second = enqueue_semantic_consolidation_job(
        session_id="sess",
        trigger_type="manual",
        window_key="manual:sess:review",
        primary_provider="openai",
        primary_model_name="gpt-4o-mini",
        secondary_provider="openai",
        secondary_model_name="gpt-4o-mini",
        candidate_ids=["cand-1"],
        queue=queue,
    )

    assert first.job_id == second.job_id
    assert first.inserted is True
    assert second.inserted is False
