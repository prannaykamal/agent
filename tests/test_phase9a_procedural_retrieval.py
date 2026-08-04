import sqlite3

import pytest

from src.db import init_db
from src.memory.retrieval_sources import retrieve_procedural_skills
from src.memory.retrieval_types import RetrievalRequest
from src.memory.skill_store import SkillVersionStore, SkillVersionWrite


@pytest.fixture
def temp_env(tmp_path, monkeypatch):
    db_file = tmp_path / "phase9a_procedural.db"
    skill_path = tmp_path / "SKILL.md"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file, skill_path


def _write(**overrides):
    data = {
        "name": "Deploy Staging",
        "description": "Deploys the app to staging.",
        "trigger_keywords": "deploy, staging",
        "execution_steps": "1. Build.\n2. Deploy to staging.\n3. Run smoke tests.",
        "preferred_tools": ["shell"],
        "tags": ["deployment", "staging"],
        "confidence": 0.9,
    }
    data.update(overrides)
    return SkillVersionWrite(**data)


def _usage(db_path, skill_id):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            "SELECT times_loaded, times_used FROM skill_usage_stats WHERE skill_id = ?",
            (skill_id,),
        ).fetchone()
    finally:
        conn.close()


def test_procedural_retrieval_reads_active_enabled_skills_only(temp_env):
    db_path, skill_path = temp_env
    store = SkillVersionStore(db_path=db_path, skill_path=skill_path)
    active = store.create_version(_write())
    disabled = store.create_version(_write(name="Archive Logs", trigger_keywords="archive, logs", skill_id="archive-logs"))
    store.disable_skill(disabled.skill_id)

    result = retrieve_procedural_skills(
        RetrievalRequest(query="deploy staging", per_source_limit=5),
        db_path=db_path,
    )

    assert [candidate.title for candidate in result.candidates] == [active.name]
    candidate = result.candidates[0]
    assert candidate.memory_kind == "procedural"
    assert candidate.provenance.table_name == "skill_versions"
    assert candidate.provenance.metadata["skill_id"] == active.skill_id
    assert candidate.provenance.metadata["preferred_tools"] == ["shell"]


def test_procedural_retrieval_reads_usage_stats_without_incrementing(temp_env):
    db_path, skill_path = temp_env
    store = SkillVersionStore(db_path=db_path, skill_path=skill_path)
    active = store.create_version(_write())
    store.record_loaded(active.skill_id, active.id)
    before = _usage(db_path, active.skill_id)

    result = retrieve_procedural_skills(RetrievalRequest(query="deploy staging"), db_path=db_path)

    assert result.candidates[0].provenance.metadata["times_loaded"] == before[0]
    assert result.candidates[0].provenance.metadata["times_used"] == before[1]
    assert _usage(db_path, active.skill_id) == before


def test_procedural_retrieval_does_not_call_reload_or_record_used(temp_env, monkeypatch):
    db_path, skill_path = temp_env
    store = SkillVersionStore(db_path=db_path, skill_path=skill_path)
    store.create_version(_write())

    def fail_record_used(*args, **kwargs):
        raise AssertionError("retrieval must not record usage")

    def fail_reload(*args, **kwargs):
        raise AssertionError("retrieval must not reload skills")

    monkeypatch.setattr(SkillVersionStore, "record_used", fail_record_used)
    monkeypatch.setattr("src.memory.skill_reloader.SkillRuntimeReloader.reload_active_skills", fail_reload)

    result = retrieve_procedural_skills(RetrievalRequest(query="deploy"), db_path=db_path)

    assert result.candidates
