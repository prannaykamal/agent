import inspect
import json
from types import SimpleNamespace

import pytest

from src.db import init_db
from src.harness.llm_router import LLMRouteResult, LLMSelector
from src.memory.procedural_candidates import ProceduralSkillCandidateStore, SkillCandidateValidationError, SkillCandidateWrite
from src.memory.procedural_dedup import (
    ProceduralDedupService,
    jaccard_score,
    tokenize_for_procedural_dedup,
    validate_dedup_decision,
)
from src.memory.skill_store import SkillVersionStore, SkillVersionWrite


@pytest.fixture
def temp_env(tmp_path, monkeypatch):
    db_file = tmp_path / "phase8b_dedup.db"
    skill_path = tmp_path / "SKILL.md"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file, skill_path


class FakeLLM:
    def __init__(self, content):
        self.content = content

    def invoke(self, prompt):
        return SimpleNamespace(content=self.content)


def _route(content):
    return LLMRouteResult(
        selector=LLMSelector("secondary", "openai", "gpt-4o-mini", 0.3, 128000, "test"),
        llm=FakeLLM(content),
        available=True,
        fallback_used=False,
    )


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


def test_deterministic_tokenizer_and_scores():
    assert tokenize_for_procedural_dedup("Deploy, deploy to staging!") == {"deploy", "staging"}
    assert jaccard_score({"deploy"}, {"deploy", "staging"}) == 0.5


def test_shortlist_scoring_order_is_deterministic(temp_env):
    db_path, _ = temp_env
    store = ProceduralSkillCandidateStore(db_path=db_path)
    strong = store.add_candidate(_write(source_job_id="job-a"))
    store.add_candidate(_write(title="Calendar Review", trigger_description="Review meetings", preferred_tools=["calendar"], tags=["calendar"], workflow_category="calendar", source_job_id="job-b"))

    matches = ProceduralDedupService(db_path=db_path, candidate_store=store).shortlist(_write(source_job_id="job-c"))

    assert matches[0].candidate_id == strong.id
    assert matches[0].trigger_score > 0
    assert matches[0].tool_score > 0
    assert matches[0].tag_score > 0
    assert matches[0].category_score == 1.0


def test_active_skills_used_read_only_for_comparison(temp_env):
    db_path, skill_path = temp_env
    SkillVersionStore(db_path=db_path, skill_path=skill_path).create_version(
        SkillVersionWrite(
            name="Deploy Staging",
            description="Deploy staging",
            trigger_keywords="deploy, staging",
            execution_steps="1. Deploy.",
            preferred_tools=["shell"],
            tags=["deploy", "staging"],
        )
    )

    matches = ProceduralDedupService(db_path=db_path, skill_store=SkillVersionStore(db_path=db_path, skill_path=skill_path)).shortlist(_write())

    assert any(match.source_type == "active_skill" and match.candidate_id == "active_skill:deploy-staging" for match in matches)


def test_no_embeddings_are_used():
    source = inspect.getsource(__import__("src.memory.procedural_dedup", fromlist=[""]))

    assert "embedding" not in source.lower()


def test_classifier_validates_exact_actions():
    decision = validate_dedup_decision({"action": "merge", "target_candidate_id": "c1", "merged_candidate_ids": ["c2"], "confidence": 0.8})

    assert decision.action == "MERGE"
    assert decision.target_candidate_id == "c1"

    with pytest.raises(SkillCandidateValidationError):
        validate_dedup_decision({"action": "PROMOTE"})


def test_classifier_parses_secondary_output(temp_env):
    db_path, _ = temp_env
    service = ProceduralDedupService(db_path=db_path)

    decision = service.classify_with_secondary(
        _route(json.dumps({"action": "DUPLICATE", "target_candidate_id": "c1", "merged_candidate_ids": [], "reason": "same", "confidence": 0.7})),
        _write(),
        [],
    )

    assert decision.action == "DUPLICATE"
    assert decision.target_candidate_id == "c1"
