from src.db import init_db
from src.memory.job_repository import MemoryJobRepository
from src.memory.jobs import (
    PHASE_8C_CREATED_BY,
    SKILL_PROMOTION_SOURCE,
    build_skill_promotion_job_spec,
    build_skill_promotion_payload,
    enqueue_skill_promotion_job,
    make_skill_promotion_idempotency_key,
)


def test_skill_promotion_payload_shape_and_flags():
    payload = build_skill_promotion_payload(
        session_id="sess",
        trigger_type="manual",
        candidate_ids=["b", "a", "a"],
        max_candidates=5,
        window_key="window-1",
    )

    assert payload["schema_version"] == 1
    assert payload["job_type"] == "skill_promotion"
    assert payload["source"] == SKILL_PROMOTION_SOURCE
    assert payload["created_by"] == PHASE_8C_CREATED_BY
    assert payload["skill_promotion"]["candidate_ids"] == ["a", "b"]
    assert payload["skill_promotion"]["approval_policy"] == "hitl_required"
    assert payload["skill_promotion"]["create_skill_files_before_approval"] is False
    assert payload["skill_promotion"]["activate_after_approval"] is True
    assert payload["skill_promotion"]["procedural_consolidation_required"] is False


def test_skill_promotion_idempotency_is_deterministic_and_order_independent():
    first = make_skill_promotion_idempotency_key(
        session_id="sess",
        trigger_type="manual",
        candidate_ids=["b", "a"],
        window_key="window-1",
    )
    second = make_skill_promotion_idempotency_key(
        session_id="sess",
        trigger_type="manual",
        candidate_ids=["a", "b"],
        window_key="window-1",
    )

    assert first == second
    assert first.startswith("memq:v1:skill_promotion:")


def test_skill_promotion_job_spec_and_duplicate_enqueue(tmp_path, monkeypatch):
    db_file = tmp_path / "phase8c_jobs.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)

    spec = build_skill_promotion_job_spec(
        session_id="sess",
        trigger_type="ready_candidate_threshold",
        candidate_ids=["candidate-1"],
    )
    assert spec.job_type == "skill_promotion"
    assert spec.priority == 80
    assert spec.job_id.startswith("memjob_skill_promotion_")

    class Queue:
        def __init__(self):
            self.repository = MemoryJobRepository(db_path=db_file)

        def enqueue_spec(self, spec):
            return self.repository.enqueue(spec)

    queue = Queue()
    first = enqueue_skill_promotion_job(
        session_id="sess",
        trigger_type="ready_candidate_threshold",
        candidate_ids=["candidate-1"],
        queue=queue,
    )
    second = enqueue_skill_promotion_job(
        session_id="sess",
        trigger_type="ready_candidate_threshold",
        candidate_ids=["candidate-1"],
        queue=queue,
    )

    assert first.job_id == second.job_id
    assert first.inserted is True
    assert second.inserted is False