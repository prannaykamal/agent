import sqlite3

import pytest

from src.db import init_db
from src.memory.procedural import (
    add_procedural_skill,
    delete_procedural_skill,
    get_all_procedural_skills,
    match_procedural_skills,
    sync_skill_md,
    sync_skills_from_md,
    update_procedural_skill,
)
from src.memory.skill_files import generated_skill_file_path, user_skill_root
from src.memory.skill_store import SkillVersionStore


@pytest.fixture
def temp_env(tmp_path, monkeypatch):
    db_file = tmp_path / "phase8a_procedural.db"
    skill_file = tmp_path / "SKILL.md"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file, skill_file


def _count(db_path, table):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def test_procedural_compatibility_functions_create_versioned_skill(temp_env):
    db_path, skill_path = temp_env

    add_procedural_skill(
        name="Automated Code Audit",
        description="Audits python files",
        trigger_keywords="audit, lint, check code",
        execution_steps="1. Run ruff, 2. Run mypy",
        db_path=db_path,
        skill_path=skill_path,
    )

    skills = get_all_procedural_skills(db_path=db_path)
    assert skills[0]["name"] == "Automated Code Audit"
    assert skills[0]["version"] == 1
    assert generated_skill_file_path("automated-code-audit", 1, skill_path).exists()
    assert "Automated Code Audit" in skill_path.read_text(encoding="utf-8")


def test_update_creates_new_version_and_match_uses_active_enabled_versions(temp_env):
    db_path, skill_path = temp_env
    add_procedural_skill("Deploy Staging", "Deploys staging", "deploy, staging", "Old steps", db_path, skill_path)
    update_procedural_skill("Deploy Staging", "New steps", db_path=db_path, skill_path=skill_path)

    versions = SkillVersionStore(db_path=db_path, skill_path=skill_path).list_versions("deploy-staging")
    assert [version.version for version in versions] == [1, 2]
    assert versions[0].active is False
    assert versions[1].active is True
    assert match_procedural_skills("please deploy to staging", db_path=db_path)[0]["execution_steps"] == "New steps"


def test_delete_disables_active_version_without_deleting_file(temp_env):
    db_path, skill_path = temp_env
    add_procedural_skill("Database Backup", "Backs up state", "backup", "Step 1", db_path, skill_path)
    path = generated_skill_file_path("database-backup", 1, skill_path)

    delete_procedural_skill("Database Backup", db_path=db_path, skill_path=skill_path)

    assert path.exists()
    assert get_all_procedural_skills(db_path=db_path) == []
    assert _count(db_path, "skill_versions") == 1


def test_sync_skills_from_md_does_not_overwrite_user_authored_files(temp_env):
    db_path, skill_path = temp_env
    user_path = user_skill_root(skill_path) / "custom" / "SKILL.md"
    user_path.parent.mkdir(parents=True, exist_ok=True)
    user_path.write_text("user-authored", encoding="utf-8")
    skill_path.write_text(
        "# Catalog\n\n"
        "### 1. API Imported Skill\n"
        "- **Description**: Imported\n"
        "- **Trigger Keywords**: import, api\n"
        "- **Action Steps**: Run imported flow\n",
        encoding="utf-8",
    )

    sync_skills_from_md(skill_path=skill_path, db_path=db_path)

    assert user_path.read_text(encoding="utf-8") == "user-authored"
    assert generated_skill_file_path("api-imported-skill", 1, skill_path).exists()


def test_sync_skill_md_preserves_user_authored_default_index(temp_env):
    db_path, skill_path = temp_env
    add_procedural_skill("Index Skill", "Desc", "index", "Step", db_path, skill_path)
    user_index = skill_path.parent / "USER_SKILL.md"
    user_index.write_text("custom index", encoding="utf-8")

    rendered = sync_skill_md(db_path=db_path, skill_path=user_index)

    assert "Index Skill" in rendered
    assert "Index Skill" in user_index.read_text(encoding="utf-8")
