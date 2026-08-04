import json
import sqlite3
from types import SimpleNamespace

import pytest

from src.db import init_db
from src.harness.llm_router import LLMRouteResult, LLMSelector
from src.memory.episode_store import StructuredEpisodeRepository, StructuredEpisodeWrite
from src.memory.job_handlers import (
    ProceduralCandidateGenerationJobHandler,
    build_default_handler_registry,
)
from src.memory.procedural_candidates import ProceduralSkillCandidateStore, SkillCandidateWrite
from src.memory.skill_store import SkillVersionStore


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "phase8b_handler.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    StructuredEpisodeRepository(db_path=db_file).append_episode(
        StructuredEpisodeWrite(
            id="episode-1",
            session_id="sess",
            title="Deploy Staging",
            summary="The user deployed a build to staging with checks.",
            participants=["User", "Assistant"],
            goals=["Deploy staging"],
            decisions=["Run smoke tests"],
            artifacts=["deploy script"],
            topics=["deploy", "staging"],
            importance=0.8,
            start_message_id="turn-1",
            end_message_id="turn-2",
            source="test",
            source_job_id="episode-job-1",
        )
    )
    return db_file


class FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def invoke(self, prompt):
        self.calls.append(prompt)
        return SimpleNamespace(content=self.responses.pop(0))


def _route(llm):
    return LLMRouteResult(
        selector=LLMSelector("secondary", "openai", "gpt-4o-mini", 0.3, 128000, "test"),
        llm=llm,
        available=llm is not None,
        fallback_used=False,
    )


def _payload():
    return {
        "schema_version": 1,
        "session_id": "sess",
        "models": {"secondary_provider": "openai", "secondary_model_name": "gpt-4o-mini"},
        "procedural_candidate_generation": {
            "schema_version": 1,
            "source": "structured_episode",
            "source_episode_id": "episode-1",
            "source_episode_ids": ["episode-1"],
            "source_episode_title": "Deploy Staging",
            "source_episode_importance": 0.8,
            "dedup_required": True,
            "create_skill_files": False,
            "promotion_allowed": False,
        },
    }


def _candidate_json(**overrides):
    candidate = {
        "title": "Deploy Staging",
        "description": "Reusable staging deployment workflow.",
        "trigger_description": "Use when deploying a build to staging.",
        "workflow_category": "deployment",
        "preferred_tools": ["shell", "github"],
        "tags": ["deploy", "staging"],
        "confidence": 0.82,
        "workflow": [{"order": 1, "instruction": "Deploy the build.", "tool_hint": "shell"}],
    }
    candidate.update(overrides)
    return json.dumps({"candidate": candidate})


def _count(db_path, table):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def test_handler_registered_and_later_procedural_jobs_remain_noop():
    registry = build_default_handler_registry()

    assert isinstance(registry["procedural_candidate_generation"], ProceduralCandidateGenerationJobHandler)
    assert registry["procedural_consolidation"].__class__.__name__ == "NoOpMemoryJobHandler"
    assert registry["skill_promotion"].__class__.__name__ == "SkillPromotionJobHandler"
    assert registry["summary_generation"].__class__.__name__ == "SummaryGenerationJobHandler"
    assert registry["episode_generation"].__class__.__name__ == "EpisodeGenerationJobHandler"


def test_secondary_unavailable_retry_writes_nothing(temp_db, monkeypatch):
    monkeypatch.setattr("src.memory.job_handlers._resolve_secondary_route", lambda payload: _route(None))

    result = ProceduralCandidateGenerationJobHandler().handle({"id": "job-1", "session_id": "sess"}, _payload())

    assert result.success is False
    assert result.retryable is True
    assert _count(temp_db, "skill_candidates") == 0


def test_candidate_null_writes_nothing(temp_db, monkeypatch):
    monkeypatch.setattr("src.memory.job_handlers._resolve_secondary_route", lambda payload: _route(FakeLLM([json.dumps({"candidate": None})])))

    result = ProceduralCandidateGenerationJobHandler().handle({"id": "job-1", "session_id": "sess"}, _payload())

    assert result.success is True
    assert result.result["processed"] is False
    assert _count(temp_db, "skill_candidates") == 0


def test_new_writes_one_skill_candidate_and_no_skill_versions_or_approvals(temp_db, monkeypatch):
    monkeypatch.setattr(SkillVersionStore, "create_version", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not create skill versions")))
    monkeypatch.setattr("src.memory.job_handlers._resolve_secondary_route", lambda payload: _route(FakeLLM([_candidate_json()])))

    result = ProceduralCandidateGenerationJobHandler().handle({"id": "job-new", "session_id": "sess"}, _payload())

    assert result.success is True
    assert result.result["dedup_action"] == "NEW"
    assert _count(temp_db, "skill_candidates") == 1
    assert _count(temp_db, "skill_versions") == 0
    assert _count(temp_db, "procedural_skill_approvals") == 0


def test_duplicate_updates_occurrence_only(temp_db, monkeypatch):
    store = ProceduralSkillCandidateStore(db_path=temp_db)
    existing = store.add_candidate(
        SkillCandidateWrite(
            title="Deploy Staging",
            description="Existing",
            trigger_description="Use when deploying a build to staging.",
            workflow=[{"order": 1, "instruction": "Deploy."}],
            preferred_tools=["shell"],
            tags=["deploy", "staging"],
            workflow_category="deployment",
            confidence=0.8,
            source_episode_ids=["episode-old"],
            source_job_id="existing-job",
        )
    )
    monkeypatch.setattr(
        "src.memory.job_handlers._resolve_secondary_route",
        lambda payload: _route(FakeLLM([_candidate_json(), json.dumps({"action": "DUPLICATE", "target_candidate_id": existing.id, "merged_candidate_ids": [], "reason": "same", "confidence": 0.8})])),
    )

    result = ProceduralCandidateGenerationJobHandler().handle({"id": "job-dup", "session_id": "sess"}, _payload())

    updated = store.get_by_id(existing.id)
    assert result.success is True
    assert result.result["dedup_action"] == "DUPLICATE"
    assert updated.occurrences == 2
    assert updated.title == "Deploy Staging"
    assert _count(temp_db, "skill_candidates") == 1


def test_update_updates_target_candidate(temp_db, monkeypatch):
    store = ProceduralSkillCandidateStore(db_path=temp_db)
    existing = store.add_candidate(
        SkillCandidateWrite(
            title="Deploy Staging",
            description="Existing",
            trigger_description="Use when deploying a build to staging.",
            workflow=[{"order": 1, "instruction": "Deploy."}],
            preferred_tools=["shell"],
            tags=["deploy"],
            workflow_category="deployment",
            confidence=0.8,
            source_episode_ids=["episode-old"],
            source_job_id="existing-job",
        )
    )
    monkeypatch.setattr(
        "src.memory.job_handlers._resolve_secondary_route",
        lambda payload: _route(FakeLLM([_candidate_json(description="Improved", workflow=[{"order": 1, "instruction": "Run smoke tests."}]), json.dumps({"action": "UPDATE", "target_candidate_id": existing.id, "merged_candidate_ids": [], "reason": "better", "confidence": 0.8})])),
    )

    result = ProceduralCandidateGenerationJobHandler().handle({"id": "job-update", "session_id": "sess"}, _payload())

    updated = store.get_by_id(existing.id)
    assert result.success is True
    assert result.result["dedup_action"] == "UPDATE"
    assert updated.description == "Improved"
    assert "Run smoke tests." in [step["instruction"] for step in updated.workflow]


def test_merge_groups_candidates_without_deleting_rows(temp_db, monkeypatch):
    store = ProceduralSkillCandidateStore(db_path=temp_db)
    first = store.add_candidate(SkillCandidateWrite("Deploy Staging", "A", "deploy staging", [{"order": 1, "instruction": "Deploy."}], ["shell"], ["deploy"], "deployment", 0.8, ["episode-a"], source_job_id="job-a"))
    second = store.add_candidate(SkillCandidateWrite("Staging Release", "B", "release staging", [{"order": 1, "instruction": "Release."}], ["github"], ["staging"], "deployment", 0.8, ["episode-b"], source_job_id="job-b"))
    monkeypatch.setattr(
        "src.memory.job_handlers._resolve_secondary_route",
        lambda payload: _route(FakeLLM([_candidate_json(), json.dumps({"action": "MERGE", "target_candidate_id": first.id, "merged_candidate_ids": [second.id], "reason": "same group", "confidence": 0.8})])),
    )

    result = ProceduralCandidateGenerationJobHandler().handle({"id": "job-merge", "session_id": "sess"}, _payload())

    assert result.success is True
    assert result.result["dedup_action"] == "MERGE"
    assert _count(temp_db, "skill_candidates") == 2
    assert store.get_by_id(first.id).dedup_group_id == store.get_by_id(second.id).dedup_group_id
