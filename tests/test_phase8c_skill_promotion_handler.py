import sqlite3

import pytest

from src.db import init_db
from src.memory.job_handlers import SkillPromotionJobHandler, build_default_handler_registry
from src.memory.jobs import build_skill_promotion_payload
from src.memory.procedural_candidates import ProceduralSkillCandidateStore, SkillCandidateWrite
from src.memory.skill_store import SkillVersionStore


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "phase8c_handler.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file


def _candidate_write(**overrides):
    data = {
        "title": "Deploy Staging",
        "description": "Reusable staging deployment workflow.",
        "trigger_description": "Use when deploying a build to staging.",
        "workflow": [{"order": 1, "instruction": "Deploy the build.", "tool_hint": "shell"}],
        "preferred_tools": ["shell", "github"],
        "tags": ["deploy", "staging"],
        "workflow_category": "deployment",
        "confidence": 0.95,
        "source_episode_ids": ["episode-1"],
        "status": "READY_FOR_PROMOTION",
        "source_job_id": "candidate-job-1",
    }
    data.update(overrides)
    return SkillCandidateWrite(**data)


def _count(db_path, table):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def test_handler_registered_and_procedural_consolidation_remains_noop():
    registry = build_default_handler_registry()

    assert isinstance(registry["skill_promotion"], SkillPromotionJobHandler)
    assert registry["procedural_consolidation"].__class__.__name__ == "NoOpMemoryJobHandler"
    assert registry["procedural_candidate_generation"].__class__.__name__ == "ProceduralCandidateGenerationJobHandler"


def test_only_ready_candidates_are_selected(temp_db):
    store = ProceduralSkillCandidateStore(db_path=temp_db)
    ready = store.add_candidate(_candidate_write(source_job_id="ready-job"))
    new = store.add_candidate(_candidate_write(title="New Candidate", source_job_id="new-job", status="NEW"))
    waiting = store.add_candidate(_candidate_write(title="Waiting Candidate", source_job_id="waiting-job", status="WAITING_FOR_APPROVAL"))

    result = SkillPromotionJobHandler().handle(
        {"id": "promotion-job", "session_id": "sess"},
        build_skill_promotion_payload(
            session_id="sess",
            trigger_type="manual",
            candidate_ids=[ready.id, new.id, waiting.id],
        ),
    )

    assert result.success is True
    assert result.result["candidate_ids"] == [ready.id]
    assert store.get_by_id(ready.id).status == "WAITING_FOR_APPROVAL"
    assert store.get_by_id(new.id).status == "NEW"
    assert store.get_by_id(waiting.id).status == "WAITING_FOR_APPROVAL"


def test_handler_creates_approval_and_link_but_no_skill_before_approval(temp_db, tmp_path, monkeypatch):
    monkeypatch.setattr(SkillVersionStore, "create_version", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not create skill versions")))
    store = ProceduralSkillCandidateStore(db_path=temp_db)
    candidate = store.add_candidate(_candidate_write())

    result = SkillPromotionJobHandler().handle(
        {"id": "promotion-job", "session_id": "sess"},
        build_skill_promotion_payload(session_id="sess", trigger_type="manual", candidate_ids=[candidate.id]),
    )

    assert result.success is True
    assert result.result["processed"] is True
    assert _count(temp_db, "approval_requests") == 1
    assert _count(temp_db, "procedural_skill_approvals") == 1
    assert _count(temp_db, "skill_versions") == 0
    assert store.get_by_id(candidate.id).status == "WAITING_FOR_APPROVAL"
    assert not (tmp_path / "skills").exists()


def test_duplicate_handler_run_reuses_existing_approval_link(temp_db):
    store = ProceduralSkillCandidateStore(db_path=temp_db)
    candidate = store.add_candidate(_candidate_write())
    payload = build_skill_promotion_payload(session_id="sess", trigger_type="manual", candidate_ids=[candidate.id])
    handler = SkillPromotionJobHandler()

    first = handler.handle({"id": "promotion-job", "session_id": "sess"}, payload)
    second = handler.handle({"id": "promotion-job", "session_id": "sess"}, payload)

    assert first.success is True
    assert second.success is True
    assert _count(temp_db, "approval_requests") == 1
    assert _count(temp_db, "procedural_skill_approvals") == 1
    assert store.get_by_id(candidate.id).status == "WAITING_FOR_APPROVAL"


def test_approval_creation_failure_leaves_candidate_ready(temp_db, monkeypatch):
    def fail_create(*args, **kwargs):
        raise RuntimeError("approval storage failed")

    monkeypatch.setattr("src.memory.skill_promotion.create_approval_request", fail_create)
    store = ProceduralSkillCandidateStore(db_path=temp_db)
    candidate = store.add_candidate(_candidate_write())

    result = SkillPromotionJobHandler().handle(
        {"id": "promotion-job", "session_id": "sess"},
        build_skill_promotion_payload(session_id="sess", trigger_type="manual", candidate_ids=[candidate.id]),
    )

    assert result.success is False
    assert result.retryable is True
    assert store.get_by_id(candidate.id).status == "READY_FOR_PROMOTION"
    assert _count(temp_db, "procedural_skill_approvals") == 0