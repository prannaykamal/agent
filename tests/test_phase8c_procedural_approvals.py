import sqlite3

import pytest

from src.db import init_db
from src.memory.procedural_candidates import ProceduralSkillCandidateStore, SkillCandidateValidationError, SkillCandidateWrite
from src.memory.skill_promotion import (
    ProceduralSkillApprovalRepository,
    create_procedural_skill_approval_request,
    select_candidates_for_skill_promotion,
)
from src.memory.skill_store import SkillVersionStore


@pytest.fixture
def temp_env(tmp_path, monkeypatch):
    db_file = tmp_path / "phase8c_approvals.db"
    skill_path = tmp_path / "SKILL.md"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    monkeypatch.setattr("src.memory.skill_files.SKILL_PATH", skill_path)
    init_db(db_file)
    return db_file, skill_path


def _write(**overrides):
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
        "source_job_id": "candidate-job",
    }
    data.update(overrides)
    return SkillCandidateWrite(**data)


def _count(db_path, table):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def test_select_candidates_skips_non_ready_and_existing_links(temp_env):
    db_path, skill_path = temp_env
    store = ProceduralSkillCandidateStore(db_path=db_path)
    repo = ProceduralSkillApprovalRepository(db_path=db_path)
    version_store = SkillVersionStore(db_path=db_path, skill_path=skill_path)
    ready = store.add_candidate(_write(source_job_id="ready"))
    other = store.add_candidate(_write(title="Other", source_job_id="other", status="OBSERVING"))

    selected = select_candidates_for_skill_promotion(
        candidate_store=store,
        approval_repo=repo,
        version_store=version_store,
        candidate_ids=[ready.id, other.id],
    )

    assert selected == [ready]


def test_create_procedural_approval_request_writes_link_after_hilt_request(temp_env):
    db_path, _ = temp_env
    store = ProceduralSkillCandidateStore(db_path=db_path)
    candidate = store.add_candidate(_write())
    repo = ProceduralSkillApprovalRepository(db_path=db_path)

    result = create_procedural_skill_approval_request(
        candidate=candidate,
        session_id="sess",
        candidate_store=store,
        approval_repo=repo,
        db_path=db_path,
    )

    assert result.approval.status == "PENDING"
    assert result.approval.candidate_id == candidate.id
    assert result.approval.action == "PROMOTE_SKILL"
    assert result.approval.modified_payload["candidate_id"] == candidate.id
    assert store.get_by_id(candidate.id).status == "WAITING_FOR_APPROVAL"
    assert _count(db_path, "approval_requests") == 1
    assert _count(db_path, "procedural_skill_approvals") == 1
    assert _count(db_path, "skill_versions") == 0


def test_create_procedural_approval_request_reuses_open_link(temp_env):
    db_path, _ = temp_env
    store = ProceduralSkillCandidateStore(db_path=db_path)
    candidate = store.add_candidate(_write())
    repo = ProceduralSkillApprovalRepository(db_path=db_path)

    first = create_procedural_skill_approval_request(candidate=candidate, session_id="sess", candidate_store=store, approval_repo=repo, db_path=db_path)
    second = create_procedural_skill_approval_request(candidate=store.get_by_id(candidate.id), session_id="sess", candidate_store=store, approval_repo=repo, db_path=db_path)

    assert second.reused is True
    assert first.approval.approval_request_id == second.approval.approval_request_id
    assert _count(db_path, "approval_requests") == 1
    assert _count(db_path, "procedural_skill_approvals") == 1


def test_illegal_transition_fails_closed(temp_env):
    db_path, _ = temp_env
    store = ProceduralSkillCandidateStore(db_path=db_path)
    candidate = store.add_candidate(_write(status="NEW"))

    with pytest.raises(SkillCandidateValidationError):
        store.transition_ready_to_waiting(candidate.id)