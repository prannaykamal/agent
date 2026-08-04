import sqlite3

import pytest
from fastapi.testclient import TestClient

from src.api.server import app
from src.db import init_db
from src.hitl.approval_engine import create_approval_request, process_approval_decision
from src.memory.procedural_candidates import ProceduralSkillCandidateStore, SkillCandidateWrite
from src.memory.skill_files import generated_skill_file_path, user_skill_root
from src.memory.skill_promotion import (
    ProceduralSkillApprovalRepository,
    create_procedural_skill_approval_request,
    process_procedural_skill_approval_decision,
)
from src.memory.skill_store import SkillVersionStore

client = TestClient(app)


@pytest.fixture
def temp_env(tmp_path, monkeypatch):
    db_file = tmp_path / "phase11_approvals.db"
    skill_path = tmp_path / "SKILL.md"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    monkeypatch.setattr("src.config.SKILL_PATH", skill_path)
    monkeypatch.setattr("src.memory.skill_files.SKILL_PATH", skill_path)
    init_db(db_file)
    return db_file, skill_path


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
        "source_job_id": "candidate-job",
    }
    data.update(overrides)
    return SkillCandidateWrite(**data)


def _candidate_approval(db_path):
    store = ProceduralSkillCandidateStore(db_path=db_path)
    candidate = store.add_candidate(_candidate_write())
    result = create_procedural_skill_approval_request(candidate=candidate, session_id="phase11", candidate_store=store, db_path=db_path)
    return store, candidate, result.approval.approval_request_id


def _count(db_path, table):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def test_non_procedural_approval_api_falls_back_to_existing_behavior(temp_env, monkeypatch):
    db_path, _ = temp_env
    request = create_approval_request(
        session_id="phase11",
        tool_name="calendar_delete_event",
        tool_args={"event_id": "evt-1"},
        reason="test non-procedural approval",
        db_path=db_path,
    )

    def fake_resume(request_id, decision):
        return {"request_id": request_id, "status": decision, "response": "legacy path"}

    monkeypatch.setattr("src.api.server.resume_graph_after_approval", fake_resume)
    response = client.post(f"/api/approvals/{request['request_id']}/decision", json={"decision": "APPROVED"})

    assert response.status_code == 200
    assert response.json()["response"] == "legacy path"
    assert _count(db_path, "procedural_skill_approvals") == 0


def test_procedural_approval_linkage_approved_creates_skill_only_after_approval(temp_env):
    db_path, skill_path = temp_env
    store, candidate, request_id = _candidate_approval(db_path)

    assert _count(db_path, "skill_versions") == 0
    assert not generated_skill_file_path("deploy-staging", 1, skill_path).exists()
    process_approval_decision(request_id, "APPROVED", db_path=db_path)
    result = process_procedural_skill_approval_decision(
        approval_request_id=request_id,
        decision="APPROVED",
        db_path=db_path,
        skill_path=skill_path,
    )

    assert result.handled is True
    assert result.skill_version_id
    assert store.get_by_id(candidate.id).status == "PROMOTED"
    assert _count(db_path, "skill_versions") == 1
    assert generated_skill_file_path("deploy-staging", 1, skill_path).exists()
    assert ProceduralSkillApprovalRepository(db_path=db_path).get_by_approval_request_id(request_id).skill_version_id == result.skill_version_id


def test_rejection_creates_no_skill_file_or_version(temp_env):
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


def test_duplicate_decision_is_idempotent_for_procedural_finalizer(temp_env):
    db_path, skill_path = temp_env
    _, _, request_id = _candidate_approval(db_path)
    process_approval_decision(request_id, "APPROVED", db_path=db_path)
    first = process_procedural_skill_approval_decision(approval_request_id=request_id, decision="APPROVED", db_path=db_path, skill_path=skill_path)
    second = process_procedural_skill_approval_decision(approval_request_id=request_id, decision="APPROVED", db_path=db_path, skill_path=skill_path)

    assert first.skill_version_id == second.skill_version_id
    assert second.message == "Procedural skill approval was already finalized"
    assert _count(db_path, "skill_versions") == 1


def test_wrong_candidate_status_fails_closed(temp_env):
    db_path, skill_path = temp_env
    store = ProceduralSkillCandidateStore(db_path=db_path)
    candidate = store.add_candidate(_candidate_write(status="NEW"))
    request = create_approval_request("phase11", "procedural_skill_promotion", {"candidate_id": candidate.id}, "test", db_path=db_path)
    ProceduralSkillApprovalRepository(db_path=db_path).create_pending_for_candidate(
        approval_request_id=request["request_id"],
        candidate_id=candidate.id,
    )
    process_approval_decision(request["request_id"], "APPROVED", db_path=db_path)

    with pytest.raises(Exception):
        process_procedural_skill_approval_decision(
            approval_request_id=request["request_id"],
            decision="APPROVED",
            db_path=db_path,
            skill_path=skill_path,
        )

    assert store.get_by_id(candidate.id).status == "NEW"
    assert _count(db_path, "skill_versions") == 0


def test_skill_version_creation_failure_leaves_waiting_candidate_recoverable(temp_env, monkeypatch):
    db_path, skill_path = temp_env
    store, candidate, request_id = _candidate_approval(db_path)
    process_approval_decision(request_id, "APPROVED", db_path=db_path)

    def fail_create(*args, **kwargs):
        raise RuntimeError("disk unavailable")

    monkeypatch.setattr(SkillVersionStore, "create_version", fail_create)

    with pytest.raises(RuntimeError):
        process_procedural_skill_approval_decision(
            approval_request_id=request_id,
            decision="APPROVED",
            db_path=db_path,
            skill_path=skill_path,
        )

    assert store.get_by_id(candidate.id).status == "WAITING_FOR_APPROVAL"
    assert ProceduralSkillApprovalRepository(db_path=db_path).get_by_approval_request_id(request_id).status == "PENDING"
    assert _count(db_path, "skill_versions") == 0


def test_approval_does_not_overwrite_user_authored_skill_files(temp_env):
    db_path, skill_path = temp_env
    user_file = user_skill_root(skill_path) / "deploy-staging" / "SKILL.md"
    user_file.parent.mkdir(parents=True)
    user_file.write_text("user-authored", encoding="utf-8")
    store, candidate, request_id = _candidate_approval(db_path)

    process_approval_decision(request_id, "APPROVED", db_path=db_path)
    process_procedural_skill_approval_decision(approval_request_id=request_id, decision="APPROVED", db_path=db_path, skill_path=skill_path)

    assert user_file.read_text(encoding="utf-8") == "user-authored"
    assert store.get_by_id(candidate.id).status == "PROMOTED"
