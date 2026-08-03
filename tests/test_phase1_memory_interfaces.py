from typing import get_args

from src.harness.models import get_model_role_config
from src.harness.state import AgentState
from src.memory.config import load_memory_config
from src.memory.interfaces import (
    EpisodicMemoryStore,
    MemoryQueue,
    ProceduralMemoryStore,
    RetrievalPlanner,
    SemanticMemoryStore,
    ShortTermMemoryManager,
    TokenCounter,
)
from src.memory.types import (
    DedupAction,
    EpisodeAction,
    FactCandidate,
    MemoryJobType,
    MemoryKind,
    RetrievedMemory,
    RetrievalRequest,
    SkillCandidateStatus,
    SkillWorkflowStep,
    SummaryBlock,
)


def test_phase1_action_and_status_literals_match_architecture():
    assert set(get_args(DedupAction)) == {"NEW", "DUPLICATE", "UPDATE", "MERGE"}
    assert set(get_args(EpisodeAction)) == {"CREATE", "UPDATE", "MERGE", "SPLIT"}
    assert set(get_args(SkillCandidateStatus)) == {
        "NEW",
        "OBSERVING",
        "READY_FOR_PROMOTION",
        "WAITING_FOR_APPROVAL",
        "PROMOTED",
        "REJECTED",
    }
    assert "semantic_candidate_extraction" in get_args(MemoryJobType)
    assert "procedural" in get_args(MemoryKind)


def test_phase1_data_models_expose_required_fields():
    summary = SummaryBlock(
        id="sum_1",
        session_id="sess_1",
        summary="Older context",
        covered_message_ids=["m1", "m2"],
        token_count=42,
        created_at="2026-08-02T00:00:00Z",
    )
    candidate = FactCandidate(
        id="fact_1",
        session_id="sess_1",
        fact="User prefers Python",
        category="preference",
        confidence=0.91,
        explicit=True,
        source="user_turn",
        created_at="2026-08-02T00:00:00Z",
    )
    step = SkillWorkflowStep(step_number=1, instruction="Run tests", optional_tools=["pytest"])
    request = RetrievalRequest(
        session_id="sess_1",
        query="What did we decide?",
        task_type="project_continuation",
        token_budget=1000,
        memory_kinds=["semantic", "episodic"],
    )
    retrieved = RetrievedMemory(
        id="mem_1",
        memory_kind="semantic",
        content="User prefers Python",
        score=0.8,
        token_count=6,
        metadata={"category": "preference"},
    )

    assert summary.covered_message_ids == ["m1", "m2"]
    assert candidate.explicit is True
    assert step.optional_tools == ["pytest"]
    assert request.memory_kinds == ["semantic", "episodic"]
    assert retrieved.metadata["category"] == "preference"


def test_phase1_interface_protocols_define_expected_methods():
    assert hasattr(TokenCounter, "count_text")
    assert hasattr(TokenCounter, "count_messages")
    assert hasattr(ShortTermMemoryManager, "prepare_context")
    assert hasattr(EpisodicMemoryStore, "retrieve")
    assert hasattr(SemanticMemoryStore, "retrieve")
    assert hasattr(ProceduralMemoryStore, "retrieve")
    assert hasattr(MemoryQueue, "enqueue")
    assert hasattr(RetrievalPlanner, "plan")


def test_phase1_agent_state_has_memory_metadata_fields():
    annotations = AgentState.__annotations__
    assert "secondary_provider" in annotations
    assert "secondary_model_name" in annotations
    assert "memory_config_version" in annotations
    assert "memory_job_ids" in annotations


def test_phase1_model_role_config_supports_different_providers():
    cfg = load_memory_config(environ={
        "PRIMARY_PROVIDER": "openai",
        "PRIMARY_MODEL": "gpt-4o",
        "SECONDARY_PROVIDER": "anthropic",
        "SECONDARY_MODEL": "claude-3-5-haiku-latest",
    })
    role_cfg = get_model_role_config(cfg)

    assert role_cfg.primary_provider == "openai"
    assert role_cfg.primary_model_name == "gpt-4o"
    assert role_cfg.primary_context_window == 128000
    assert role_cfg.secondary_provider == "anthropic"
    assert role_cfg.secondary_model_name == "claude-3-5-haiku-latest"
    assert role_cfg.secondary_context_window == 200000
