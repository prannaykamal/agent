import pytest
from fastapi.testclient import TestClient

from src.api import server
from src.db import init_db
from src.memory.procedural_candidates import ProceduralSkillCandidateStore, SkillCandidateWrite
from src.memory.skill_promotion import create_procedural_skill_approval_request


@pytest.fixture
def temp_env(tmp_path, monkeypatch):
    db_file = tmp_path / "phase8c_api.db"
    skill_path = tmp_path / "SKILL.md"
    memory_path = tmp_path / "MEMORY.md"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    monkeypatch.setattr("src.memory.skill_files.SKILL_PATH", skill_path)
    monkeypatch.setattr("src.config.MEMORY_PATH", memory_path)
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


def test_non_procedural_approval_decision_uses_existing_graph_path(temp_env, monkeypatch):
    called = {}

    def fake_resume(request_id, decision):
        called["args"] = (request_id, decision)
        return {"request_id": request_id, "status": decision, "message": "existing path"}

    monkeypatch.setattr(server, "resume_graph_after_approval", fake_resume)
    client = TestClient(server.app)

    response = client.post("/api/approvals/req-non-proc/decision", json={"decision": "APPROVED"})

    assert response.status_code == 200
    assert response.json()["message"] == "existing path"
    assert called["args"] == ("req-non-proc", "APPROVED")


def test_procedural_approval_decision_finalizes_promotion(temp_env):
    db_path, skill_path = temp_env
    store = ProceduralSkillCandidateStore(db_path=db_path)
    candidate = store.add_candidate(_write())
    created = create_procedural_skill_approval_request(candidate=candidate, session_id="sess", candidate_store=store, db_path=db_path)
    client = TestClient(server.app)

    response = client.post(f"/api/approvals/{created.approval.approval_request_id}/decision", json={"decision": "APPROVED"})

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "APPROVED"
    assert data["tool_name"] == "procedural_skill_promotion"
    assert data["procedural_skill_approval"]["handled"] is True
    assert data["procedural_skill_approval"]["skill_version_id"]
    assert store.get_by_id(candidate.id).status == "PROMOTED"


def test_api_skills_and_memory_full_shapes_unchanged(temp_env):
    client = TestClient(server.app)

    skills = client.get("/api/skills")
    full = client.get("/api/memory/full?query=deploy")

    assert skills.status_code == 200
    assert set(["skills", "total_skills"]).issubset(skills.json().keys())
    assert full.status_code == 200
    assert set(["facts", "episodes", "soul_md", "skill_md", "memory_md"]).issubset(full.json().keys())