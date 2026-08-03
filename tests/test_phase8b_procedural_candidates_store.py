import json
import sqlite3

import pytest

from src.db import init_db
from src.memory.procedural_candidates import (
    ProceduralSkillCandidateStore,
    SkillCandidateValidationError,
    SkillCandidateWrite,
)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "phase8b_candidates.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file


def _write(**overrides):
    data = {
        "title": "Deploy Staging",
        "description": "Reusable staging deployment workflow.",
        "trigger_description": "Use when deploying a build to staging.",
        "workflow": [{"order": 1, "instruction": "Deploy the build.", "tool_hint": "shell"}],
        "preferred_tools": ["shell", "github"],
        "tags": ["deploy", "staging"],
        "workflow_category": "deployment",
        "confidence": 0.82,
        "source_episode_ids": ["episode-1"],
        "source_job_id": "job-1",
    }
    data.update(overrides)
    return SkillCandidateWrite(**data)


def _rows(db_path, table):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in conn.execute(f"SELECT * FROM {table}").fetchall()]
    finally:
        conn.close()


def test_candidate_validation(temp_db):
    with pytest.raises(SkillCandidateValidationError) as exc:
        ProceduralSkillCandidateStore(db_path=temp_db).add_candidate(_write(title=" "))

    assert exc.value.field == "title"


def test_canonical_json_storage_and_add_get_list(temp_db):
    store = ProceduralSkillCandidateStore(db_path=temp_db)

    record = store.add_candidate(_write(preferred_tools=["github", "shell"], tags=["staging", "deploy"]))

    row = _rows(temp_db, "skill_candidates")[0]
    assert json.loads(row["workflow_json"])[0]["instruction"] == "Deploy the build."
    assert row["preferred_tools_json"] == '["github","shell"]'
    assert row["tags_json"] == '["deploy","staging"]'
    assert row["source_episode_ids_json"] == '["episode-1"]'
    assert store.get_by_id(record.id) == record
    assert store.list_by_status("NEW") == [record]
    assert store.list_for_episode("episode-1") == [record]


def test_source_job_id_idempotency(temp_db):
    store = ProceduralSkillCandidateStore(db_path=temp_db)

    first = store.add_candidate(_write())
    second = store.add_candidate(_write(title="Different title"))

    assert first.id == second.id
    assert len(_rows(temp_db, "skill_candidates")) == 1


def test_occurrence_confidence_and_ready_for_promotion(temp_db):
    store = ProceduralSkillCandidateStore(db_path=temp_db)
    first = store.add_candidate(_write(confidence=0.91))

    second = store.apply_duplicate(first, _write(source_job_id="job-2", source_episode_ids=["episode-2"], confidence=0.92))
    third = store.apply_duplicate(second, _write(source_job_id="job-3", source_episode_ids=["episode-3"], confidence=0.93))

    assert third.occurrences == 3
    assert third.confidence >= 0.93
    assert third.status == "READY_FOR_PROMOTION"
    assert third.source_episode_ids == ["episode-1", "episode-2", "episode-3"]


def test_update_and_merge_do_not_touch_skill_version_or_approval_tables(temp_db):
    store = ProceduralSkillCandidateStore(db_path=temp_db)
    first = store.add_candidate(_write(source_job_id="job-a", source_episode_ids=["episode-a"]))
    second = store.add_candidate(_write(title="Staging Release", source_job_id="job-b", source_episode_ids=["episode-b"]))

    updated = store.apply_update(first, _write(source_job_id="job-c", source_episode_ids=["episode-c"], workflow=[{"order": 1, "instruction": "Run smoke tests."}]))
    merged = store.apply_merge([updated, second], _write(source_job_id="job-d", source_episode_ids=["episode-d"]))

    assert "Run smoke tests." in [step["instruction"] for step in updated.workflow]
    assert merged.dedup_group_id
    assert len(_rows(temp_db, "skill_candidates")) == 2
    assert len(_rows(temp_db, "skill_versions")) == 0
    assert len(_rows(temp_db, "procedural_skill_approvals")) == 0
