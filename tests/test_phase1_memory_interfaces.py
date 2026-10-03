from typing import get_args

from src.harness.models import get_model_role_config
from src.harness.state import AgentState
from src.memory.config import load_memory_config
from src.memory.interfaces import (
    LongTermMemoryStore,
    MemoryQueue,
    RetrievalPlanner,
    ShortTermMemoryManager,
    TokenCounter,
)
from src.memory.types import (
    MemoryJobType,
    MemoryKind,
    RetrievedMemory,
    RetrievalRequest,
    SummaryBlock,
)


def test_memory_literals_reflect_cognee_architecture():
    assert set(get_args(MemoryJobType)) == {"summary_generation", "cognee_ingest", "memory_session_write", "memory_session_merge"}
    assert set(get_args(MemoryKind)) == {"short_term", "summary", "long_term"}


def test_phase1_data_models_expose_required_fields():
    summary = SummaryBlock(
        id="sum_1",
        session_id="sess_1",
        summary="Older context",
        covered_message_ids=["m1", "m2"],
        token_count=42,
        created_at="2026-08-02T00:00:00Z",
    )
    request = RetrievalRequest(
        session_id="sess_1",
        query="What did we decide?",
        task_type="project_continuation",
        token_budget=1000,
        memory_kinds=["long_term"],
    )
    retrieved = RetrievedMemory(
        id="mem_1",
        memory_kind="long_term",
        content="User prefers Python",
        score=0.8,
        token_count=6,
        metadata={"category": "preference"},
    )

    assert summary.covered_message_ids == ["m1", "m2"]
    assert request.memory_kinds == ["long_term"]
    assert retrieved.metadata["category"] == "preference"


def test_phase1_interface_protocols_define_expected_methods():
    assert hasattr(TokenCounter, "count_text")
    assert hasattr(TokenCounter, "count_messages")
    assert hasattr(ShortTermMemoryManager, "prepare_context")
    assert hasattr(LongTermMemoryStore, "retrieve")
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
