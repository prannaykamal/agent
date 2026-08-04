import sqlite3

import pytest

from src.db import init_db
from src.hitl.approval_engine import process_approval_decision
from src.memory.procedural_candidates import ProceduralSkillCandidateStore, SkillCandidateWrite
from src.memory.skill_files import generated_skill_file_path, user_skill_root
from src.memory.skill_promotion import (
    ProceduralSkillApprovalRepository,
    create_procedural_skill_approval_request,
    process_procedural_skill_approval_decision,
    resume_approved_skill_promotions,
)
from src.memory.skill_store import SkillVersionStore, SkillVersionWrite


@pytest.fixture
def temp_env(tmp_path, monkeypatch):
    db_file = tmp_path / "phase8c_decisions.db"
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
        "workflow": [
            {"order": 2, "instruction": "Run smoke tests.", "tool_hint": "shell"},
            {"order": 1, "instruction": "Deploy the build.", "tool_hint": "github"},
        ],
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


def _candidate_approval(db_path):
    store = ProceduralSkillCandidateStore(db_path=db_path)
    candidate = store.add_candidate(_write())
    result = create_procedural_skill_approval_request(candidate=candidate, session_id="sess", candidate_store=store, db_path=db_path)
    return store, candidate, result.approval.approval_request_id


def _count(db_path, table):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def test_rejection_marks_candidate_rejected_and_creates_no_skill(temp_env):
    db_path, skill_path = temp_env
    store, candidate, request_id = _candidate_approval(db_path)

    process_approval_decision(request_id, "REJECTED", db_path=db_path)
    result = process_procedural_skill_approval_decision(
        approval_request_id=request_id,
        decision="REJECTED",
        db_path=db_path,
        skill_path=skill_path,
    )

    assert result.handled is True
    assert result.status == "REJECTED"
    assert store.get_by_id(candidate.id).status == "REJECTED"
    assert _count(db_path, "skill_versions") == 0
    assert not generated_skill_file_path("deploy-staging", 1, skill_path).exists()


def test_approval_creates_generated_skill_through_store_and_promotes_candidate(temp_env):
    db_path, skill_path = temp_env
    store, candidate, request_id = _candidate_approval(db_path)

    process_approval_decision(request_id, "APPROVED", db_path=db_path)
    result = process_procedural_skill_approval_decision(
        approval_request_id=request_id,
        decision="APPROVED",
        db_path=db_path,
        skill_path=skill_path,
    )

    version = SkillVersionStore(db_path=db_path, skill_path=skill_path).get_version(result.skill_version_id)
    link = ProceduralSkillApprovalRepository(db_path=db_path).get_by_approval_request_id(request_id)
    assert result.handled is True
    assert result.status == "APPROVED"
    assert version is not None
    assert version.candidate_id == candidate.id
    assert version.author == "generated"
    assert version.approval_required is True
    assert version.approval_id == request_id
    assert version.active is True
    assert generated_skill_file_path("deploy-staging", 1, skill_path).exists()
    assert store.get_by_id(candidate.id).status == "PROMOTED"
    assert link.skill_version_id == version.id


def test_approval_does_not_overwrite_user_authored_or_old_generated_files(temp_env):
    db_path, skill_path = temp_env
    user_dir = user_skill_root(skill_path) / "deploy-staging"
    user_dir.mkdir(parents=True)
    user_file = user_dir / "SKILL.md"
    user_file.write_text("user-authored", encoding="utf-8")
    store_versions = SkillVersionStore(db_path=db_path, skill_path=skill_path)
    first = store_versions.create_version(
        SkillVersionWrite(
            name="Deploy Staging",
            description="Existing approved skill.",
            trigger_keywords="deploy, staging",
            execution_steps="1. Existing flow.",
        )
    )
    first_path = generated_skill_file_path("deploy-staging", 1, skill_path)
    first_content = first_path.read_text(encoding="utf-8")
    store, candidate, request_id = _candidate_approval(db_path)

    process_approval_decision(request_id, "APPROVED", db_path=db_path)
    result = process_procedural_skill_approval_decision(approval_request_id=request_id, decision="APPROVED", db_path=db_path, skill_path=skill_path)

    assert first.version == 1
    assert SkillVersionStore(db_path=db_path, skill_path=skill_path).get_version(result.skill_version_id).version == 2
    assert first_path.read_text(encoding="utf-8") == first_content
    assert user_file.read_text(encoding="utf-8") == "user-authored"
    assert store.get_by_id(candidate.id).status == "PROMOTED"


def test_resume_approved_skill_promotions_recovers_pending_link(temp_env):
    db_path, skill_path = temp_env
    store, candidate, request_id = _candidate_approval(db_path)
    process_approval_decision(request_id, "APPROVED", db_path=db_path)

    results = resume_approved_skill_promotions(db_path=db_path, skill_path=skill_path)

    assert len(results) == 1
    assert results[0].skill_version_id
    assert store.get_by_id(candidate.id).status == "PROMOTED"