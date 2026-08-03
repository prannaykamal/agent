import pytest
from fastapi.testclient import TestClient
from src.db import init_db
from src.memory.procedural import (
    add_procedural_skill,
    update_procedural_skill,
    delete_procedural_skill,
    get_all_procedural_skills,
    match_procedural_skills,
    sync_skill_md
)
from src.api.server import app

@pytest.fixture
def temp_env(tmp_path, monkeypatch):
    db_file = tmp_path / "test_procedural.db"
    skill_file = tmp_path / "SKILL.md"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file, skill_file

client = TestClient(app)

def test_add_and_get_procedural_skills(temp_env):
    db_file, skill_file = temp_env

    add_procedural_skill(
        name="Automated Code Audit",
        description="Audits python files",
        trigger_keywords="audit, lint, check code",
        execution_steps="1. Run ruff, 2. Run mypy",
        db_path=db_file,
        skill_path=skill_file
    )

    skills = get_all_procedural_skills(db_path=db_file)
    assert len(skills) >= 1
    assert skills[0]["name"] == "Automated Code Audit"

    # Verify SKILL.md file auto-sync
    assert skill_file.exists()
    content = skill_file.read_text(encoding="utf-8")
    assert "Automated Code Audit" in content
    assert "Run ruff" in content

def test_match_procedural_skills(temp_env):
    db_file, skill_file = temp_env

    add_procedural_skill(
        name="Deploy Staging",
        description="Deploys to staging server",
        trigger_keywords="deploy, release, staging",
        execution_steps="Deploy build v1",
        db_path=db_file,
        skill_path=skill_file
    )

    matched = match_procedural_skills("Please deploy to staging", db_path=db_file)
    assert len(matched) >= 1
    assert matched[0]["name"] == "Deploy Staging"

def test_update_and_delete_procedural_skill(temp_env):
    db_file, skill_file = temp_env

    add_procedural_skill(
        name="Database Backup",
        description="Backs up state.db",
        trigger_keywords="backup, dump",
        execution_steps="Step 1",
        db_path=db_file,
        skill_path=skill_file
    )

    update_procedural_skill("Database Backup", "Step 1 and Step 2", db_path=db_file, skill_path=skill_file)
    skills = get_all_procedural_skills(db_path=db_file)
    assert skills[0]["execution_steps"] == "Step 1 and Step 2"

    delete_procedural_skill("Database Backup", db_path=db_file, skill_path=skill_file)
    skills = get_all_procedural_skills(db_path=db_file)
    assert len(skills) == 0

def test_api_skills_endpoints(temp_env):
    post_resp = client.post(
        "/api/skills",
        json={
            "name": "API Test Skill",
            "description": "Test skill via REST API",
            "trigger_keywords": "api, test",
            "execution_steps": "Run API tests"
        }
    )
    assert post_resp.status_code == 200
    assert post_resp.json()["status"] == "success"

    get_resp = client.get("/api/skills")
    assert get_resp.status_code == 200
    assert get_resp.json()["total_skills"] >= 1

    del_resp = client.delete("/api/skills/API%20Test%20Skill")
    assert del_resp.status_code == 200
    assert del_resp.json()["status"] == "success"
