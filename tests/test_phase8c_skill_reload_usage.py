import sqlite3

import pytest

from src.db import init_db
from src.memory.skill_reloader import SkillRuntimeReloader
from src.memory.skill_store import SkillVersionStore, SkillVersionWrite


@pytest.fixture
def temp_env(tmp_path, monkeypatch):
    db_file = tmp_path / "phase8c_reload.db"
    skill_path = tmp_path / "SKILL.md"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    monkeypatch.setattr("src.memory.skill_files.SKILL_PATH", skill_path)
    init_db(db_file)
    return db_file, skill_path


def _usage_row(db_path, skill_id):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM skill_usage_stats WHERE skill_id = ?", (skill_id,)).fetchone()
        return dict(row)
    finally:
        conn.close()


def test_reload_active_skills_records_times_loaded(temp_env):
    db_path, skill_path = temp_env
    record = SkillVersionStore(db_path=db_path, skill_path=skill_path).create_version(
        SkillVersionWrite(
            name="Deploy Staging",
            description="Deploys to staging.",
            trigger_keywords="deploy, staging",
            execution_steps="1. Deploy.",
        )
    )
    reloader = SkillRuntimeReloader(db_path=db_path, skill_path=skill_path)

    snapshot = reloader.reload_active_skills()

    assert reloader.last_error is None
    assert len(snapshot.skills) == 1
    assert snapshot.skills[0].version_id == record.id
    assert _usage_row(db_path, record.skill_id)["times_loaded"] == 1


def test_record_skill_used_records_times_used(temp_env):
    db_path, skill_path = temp_env
    record = SkillVersionStore(db_path=db_path, skill_path=skill_path).create_version(
        SkillVersionWrite(
            name="Deploy Staging",
            description="Deploys to staging.",
            trigger_keywords="deploy, staging",
            execution_steps="1. Deploy.",
        )
    )
    reloader = SkillRuntimeReloader(db_path=db_path, skill_path=skill_path)

    stats = reloader.record_skill_used(record.skill_id)

    assert stats.times_used == 1
    assert stats.active_version_id == record.id
    assert _usage_row(db_path, record.skill_id)["times_used"] == 1


def test_reload_failure_keeps_previous_snapshot(temp_env):
    db_path, skill_path = temp_env
    record = SkillVersionStore(db_path=db_path, skill_path=skill_path).create_version(
        SkillVersionWrite(
            name="Deploy Staging",
            description="Deploys to staging.",
            trigger_keywords="deploy, staging",
            execution_steps="1. Deploy.",
        )
    )
    reloader = SkillRuntimeReloader(db_path=db_path, skill_path=skill_path)
    first = reloader.reload_active_skills()
    assert len(first.skills) == 1

    path = first.skills[0].file_path
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("broken")
    second = reloader.reload_active_skills()

    assert second == first
    assert reloader.last_error is not None
    assert _usage_row(db_path, record.skill_id)["times_loaded"] == 1