import sqlite3

import pytest

from src.db import init_db
from src.memory.skill_files import generated_skill_file_path
from src.memory.skill_store import SkillVersionStore, SkillVersionWrite


@pytest.fixture
def temp_env(tmp_path, monkeypatch):
    db_file = tmp_path / "phase8a_store.db"
    skill_path = tmp_path / "SKILL.md"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file, skill_path


def _count(db_path, table):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def _write(**overrides):
    data = {
        "name": "Deploy Staging",
        "description": "Deploys to staging.",
        "trigger_keywords": "deploy, staging",
        "execution_steps": "1. Deploy the build.",
    }
    data.update(overrides)
    return SkillVersionWrite(**data)


def test_create_first_version_and_usage_stats_initialized(temp_env):
    db_path, skill_path = temp_env
    store = SkillVersionStore(db_path=db_path, skill_path=skill_path)

    record = store.create_version(_write())

    assert record.skill_id == "deploy-staging"
    assert record.version == 1
    assert record.active is True
    assert record.enabled is True
    assert generated_skill_file_path("deploy-staging", 1, skill_path).exists()
    assert _count(db_path, "skill_versions") == 1
    assert _count(db_path, "skill_usage_stats") == 1
    assert _count(db_path, "skill_candidates") == 0
    assert _count(db_path, "procedural_skill_approvals") == 0


def test_update_creates_second_version_and_old_file_is_unchanged(temp_env):
    db_path, skill_path = temp_env
    store = SkillVersionStore(db_path=db_path, skill_path=skill_path)
    first = store.create_version(_write())
    first_path = generated_skill_file_path("deploy-staging", 1, skill_path)
    old_content = first_path.read_text(encoding="utf-8")

    second = store.create_version(_write(execution_steps="1. Deploy. 2. Smoke test."))

    assert first.id != second.id
    assert second.version == 2
    assert first_path.read_text(encoding="utf-8") == old_content
    assert generated_skill_file_path("deploy-staging", 2, skill_path).exists()
    assert store.get_active_version("deploy-staging").id == second.id
    assert [version.active for version in store.list_versions("deploy-staging")] == [False, True]


def test_rollback_activates_older_version_without_rewriting_files(temp_env):
    db_path, skill_path = temp_env
    store = SkillVersionStore(db_path=db_path, skill_path=skill_path)
    store.create_version(_write())
    store.create_version(_write(execution_steps="1. New steps."))
    first_path = generated_skill_file_path("deploy-staging", 1, skill_path)
    first_content = first_path.read_text(encoding="utf-8")

    rolled_back = store.rollback_to_version("deploy-staging", 1)

    assert rolled_back.version == 1
    assert store.get_active_version("deploy-staging").version == 1
    assert first_path.read_text(encoding="utf-8") == first_content
    assert [version.active for version in store.list_versions("deploy-staging")] == [True, False]


def test_disabled_version_excluded_from_active_list(temp_env):
    db_path, skill_path = temp_env
    store = SkillVersionStore(db_path=db_path, skill_path=skill_path)
    record = store.create_version(_write())

    disabled = store.disable_skill(record.skill_id)

    assert disabled.enabled is False
    assert disabled.active is False
    assert disabled.archived_at is not None
    assert store.list_active_versions() == []
    assert generated_skill_file_path("deploy-staging", 1, skill_path).exists()


def test_usage_stats_loaded_and_used_increment(temp_env):
    db_path, skill_path = temp_env
    store = SkillVersionStore(db_path=db_path, skill_path=skill_path)
    record = store.create_version(_write())

    loaded = store.record_loaded(record.skill_id, record.id)
    used = store.record_used(record.skill_id, record.id)

    assert loaded.times_loaded == 1
    assert used.times_used == 1
    assert used.active_version_id == record.id
