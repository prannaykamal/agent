import json
import sqlite3
from types import SimpleNamespace

import pytest

from src.db import init_db
from src.harness.llm_router import LLMRouteResult, LLMSelector
from src.memory.episode_store import StructuredEpisodeRepository, StructuredEpisodeWrite
from src.memory.job_handlers import ProceduralCandidateGenerationJobHandler, build_default_handler_registry
from src.memory.procedural_candidates import ProceduralSkillCandidateStore, SkillCandidateWrite
from src.memory.skill_files import generated_skill_file_path, user_skill_root
from src.memory.skill_reloader import SkillRuntimeReloader
from src.memory.skill_store import SkillVersionStore, SkillVersionWrite


@pytest.fixture
def temp_env(tmp_path, monkeypatch):
    db_file = tmp_path / "phase11_procedural.db"
    skill_path = tmp_path / "SKILL.md"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    monkeypatch.setattr("src.config.SKILL_PATH", skill_path)
    monkeypatch.setattr("src.memory.skill_files.SKILL_PATH", skill_path)
    init_db(db_file)
    StructuredEpisodeRepository(db_path=db_file).append_episode(
        StructuredEpisodeWrite(
            id="episode-1",
            session_id="phase11-procedural",
            title="Deploy Staging",
            summary="The user deployed staging with smoke checks.",
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
    return db_file, skill_path


class FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def invoke(self, prompt):
        self.calls.append(prompt)
        return SimpleNamespace(content=self.responses.pop(0))


def _route(llm):
    return LLMRouteResult(LLMSelector("secondary", "openai", "gpt-4o-mini", 0.3, 128000, "test"), llm, llm is not None, False)


def _payload():
    return {
        "schema_version": 1,
        "session_id": "phase11-procedural",
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
        "confidence": 0.95,
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


def test_procedural_candidate_handler_registered_and_consolidation_noop():
    registry = build_default_handler_registry()

    assert isinstance(registry["procedural_candidate_generation"], ProceduralCandidateGenerationJobHandler)
    assert registry["procedural_consolidation"].__class__.__name__ == "NoOpMemoryJobHandler"


def test_candidate_null_writes_nothing(temp_env, monkeypatch):
    db_path, _ = temp_env
    monkeypatch.setattr("src.memory.job_handlers._resolve_secondary_route", lambda payload: _route(FakeLLM([json.dumps({"candidate": None})])))

    result = ProceduralCandidateGenerationJobHandler().handle({"id": "job-null", "session_id": "phase11-procedural"}, _payload())

    assert result.success is True
    assert result.result["processed"] is False
    assert _count(db_path, "skill_candidates") == 0


def test_new_candidate_writes_only_skill_candidates_before_approval(temp_env, monkeypatch):
    db_path, skill_path = temp_env
    monkeypatch.setattr("src.memory.job_handlers._resolve_secondary_route", lambda payload: _route(FakeLLM([_candidate_json()])))

    result = ProceduralCandidateGenerationJobHandler().handle({"id": "job-new", "session_id": "phase11-procedural"}, _payload())

    assert result.success is True
    assert _count(db_path, "skill_candidates") == 1
    assert _count(db_path, "skill_versions") == 0
    assert _count(db_path, "procedural_skill_approvals") == 0
    assert not generated_skill_file_path("deploy-staging", 1, skill_path).exists()


def test_candidate_dedup_updates_skill_candidates_only(temp_env, monkeypatch):
    db_path, _ = temp_env
    store = ProceduralSkillCandidateStore(db_path=db_path)
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

    result = ProceduralCandidateGenerationJobHandler().handle({"id": "job-dup", "session_id": "phase11-procedural"}, _payload())

    assert result.success is True
    assert result.result["dedup_action"] == "DUPLICATE"
    assert store.get_by_id(existing.id).occurrences == 2
    assert _count(db_path, "skill_candidates") == 1
    assert _count(db_path, "skill_versions") == 0
    assert _count(db_path, "procedural_skill_approvals") == 0


def test_reload_failure_keeps_previous_snapshot_and_user_skill_is_not_overwritten(temp_env):
    db_path, skill_path = temp_env
    user_file = user_skill_root(skill_path) / "deploy-staging" / "SKILL.md"
    user_file.parent.mkdir(parents=True)
    user_file.write_text("user-authored", encoding="utf-8")
    record = SkillVersionStore(db_path=db_path, skill_path=skill_path).create_version(
        SkillVersionWrite(
            name="Deploy Staging",
            description="Deploys staging.",
            trigger_keywords="deploy, staging",
            execution_steps="1. Deploy.",
        )
    )
    reloader = SkillRuntimeReloader(db_path=db_path, skill_path=skill_path)
    first = reloader.reload_active_skills()
    generated_path = generated_skill_file_path(record.skill_id, record.version, skill_path)
    old_generated = generated_path.read_text(encoding="utf-8")

    generated_path.write_text("broken", encoding="utf-8")
    second = reloader.reload_active_skills()

    assert second == first
    assert reloader.last_error is not None
    assert user_file.read_text(encoding="utf-8") == "user-authored"
    assert old_generated != ""
