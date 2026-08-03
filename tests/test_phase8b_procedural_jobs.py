import pytest

from src.db import init_db
from src.memory.job_repository import MemoryJobRepository
from src.memory.jobs import (
    build_procedural_candidate_generation_job_spec,
    build_procedural_candidate_generation_payload,
    enqueue_procedural_candidate_generation_job,
    make_procedural_candidate_generation_idempotency_key,
)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "phase8b_jobs.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file


def test_payload_shape_and_idempotency():
    payload = build_procedural_candidate_generation_payload(
        session_id="sess",
        source_episode_id="episode-1",
        source_episode_title="Deploy Staging",
        source_episode_importance=0.8,
        primary_provider="xai",
        primary_model_name="grok-3",
        secondary_provider="unknown",
        secondary_model_name="gpt-4o-mini",
    )

    assert payload["schema_version"] == 1
    assert payload["models"]["primary_provider"] == "grok"
    assert payload["models"]["secondary_provider"] == "openai"
    assert payload["procedural_candidate_generation"]["create_skill_files"] is False
    assert payload["procedural_candidate_generation"]["promotion_allowed"] is False

    first = make_procedural_candidate_generation_idempotency_key(
        session_id="sess",
        source_episode_ids=["episode-1"],
        source_episode_title="Deploy Staging",
        secondary_provider="openai",
        secondary_model_name="gpt-4o-mini",
    )
    second = make_procedural_candidate_generation_idempotency_key(
        session_id="sess",
        source_episode_ids=["episode-1"],
        source_episode_title="Deploy Staging",
        secondary_provider="openai",
        secondary_model_name="gpt-4o-mini",
    )
    assert first == second


def test_job_spec_and_duplicate_enqueue_reuses_row(temp_db):
    spec = build_procedural_candidate_generation_job_spec(
        session_id="sess",
        source_episode_id="episode-1",
        source_episode_title="Deploy Staging",
        source_episode_importance=0.8,
        primary_provider="openai",
        primary_model_name="gpt-4o-mini",
        secondary_provider="openai",
        secondary_model_name="gpt-4o-mini",
    )

    assert spec.job_type == "procedural_candidate_generation"
    assert spec.priority == 80
    assert spec.job_id.startswith("memjob_procedural_candidate_generation_")

    class Queue:
        def __init__(self):
            self.repository = MemoryJobRepository(db_path=temp_db)

        def enqueue_spec(self, spec):
            return self.repository.enqueue(spec)

    queue = Queue()
    first = enqueue_procedural_candidate_generation_job(
        session_id="sess",
        source_episode_id="episode-1",
        source_episode_title="Deploy Staging",
        source_episode_importance=0.8,
        primary_provider="openai",
        primary_model_name="gpt-4o-mini",
        secondary_provider="openai",
        secondary_model_name="gpt-4o-mini",
        queue=queue,
    )
    second = enqueue_procedural_candidate_generation_job(
        session_id="sess",
        source_episode_id="episode-1",
        source_episode_title="Deploy Staging",
        source_episode_importance=0.8,
        primary_provider="openai",
        primary_model_name="gpt-4o-mini",
        secondary_provider="openai",
        secondary_model_name="gpt-4o-mini",
        queue=queue,
    )

    assert first.job_id == second.job_id
    assert first.inserted is True
    assert second.inserted is False
