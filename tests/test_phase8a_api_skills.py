import sqlite3

import pytest
from fastapi.testclient import TestClient

from src.api.server import app
from src.db import init_db
from src.memory.skill_files import generated_skill_file_path


@pytest.fixture
def temp_env(tmp_path, monkeypatch):
    db_file = tmp_path / "phase8a_api.db"
    skill_file = tmp_path / "SKILL.md"
    memory_file = tmp_path / "MEMORY.md"
    soul_file = tmp_path / "SOUL.md"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    monkeypatch.setattr("src.memory.skill_files.SKILL_PATH", skill_file)
    monkeypatch.setattr("src.memory.procedural.SKILL_PATH", skill_file)
    monkeypatch.setattr("src.api.server.SKILL_PATH", skill_file)
    monkeypatch.setattr("src.api.server.MEMORY_PATH", memory_file)
    monkeypatch.setattr("src.api.server.SOUL_PATH", soul_file)
    memory_file.write_text("# Memory\n", encoding="utf-8")
    soul_file.write_text("# Soul\n", encoding="utf-8")
    init_db(db_file)
    return db_file, skill_file


def _count(db_path, table):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def test_api_skill_routes_remain_compatible(temp_env):
    db_path, skill_path = temp_env
    client = TestClient(app)

    post_resp = client.post(
        "/api/skills",
        json={
            "name": "API Test Skill",
            "description": "Test skill via REST API",
            "trigger_keywords": "api, test",
            "execution_steps": "Run API tests",
        },
    )
    assert post_resp.status_code == 200
    assert post_resp.json()["status"] == "success"
    assert generated_skill_file_path("api-test-skill", 1, skill_path).exists()

    get_resp = client.get("/api/skills")
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert "skills" in data
    assert "total_skills" in data
    assert data["total_skills"] >= 1
    skill = next(item for item in data["skills"] if item["name"] == "API Test Skill")
    assert skill["version"] == 1
    assert skill["active"] is True
    assert "execution_steps" in skill

    del_resp = client.delete("/api/skills/API%20Test%20Skill")
    assert del_resp.status_code == 200
    assert del_resp.json()["status"] == "success"
    assert _count(db_path, "skill_versions") == 1
    assert _count(db_path, "skill_candidates") == 0
    assert _count(db_path, "procedural_skill_approvals") == 0


def test_api_memory_full_shape_unchanged(temp_env):
    _, _ = temp_env
    client = TestClient(app)

    response = client.get("/api/memory/full")

    assert response.status_code == 200
    data = response.json()
    assert set(data) == {"facts", "episodes", "soul_md", "skill_md", "memory_md"}
