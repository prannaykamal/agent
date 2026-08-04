from dataclasses import dataclass

import pytest
from langchain_core.messages import HumanMessage

from src.memory.retrieval_planner import (
    allocate_retrieval_budget,
    build_retrieval_plan,
    classify_retrieval_task,
    select_memory_kinds,
)


@dataclass(frozen=True)
class FakeBudget:
    provider: str = "openai"
    model_name: str = "gpt-4o-mini"
    context_window: int = 8000
    conversation_budget_tokens: int = 3000
    summarization_trigger_tokens: int = 2700
    historical_conversation_tokens: int = 100
    current_user_message_tokens: int = 20
    system_prompt_tokens: int = 0
    tool_schema_tokens: int = 0
    retrieved_memory_tokens: int = 0
    output_reserve_tokens: int = 800
    safety_margin_tokens: int = 400
    reserved_tokens: int = 1200
    available_input_tokens: int = 6800
    budget_usage_ratio: float = 0.03
    trigger_usage_ratio: float = 0.04
    should_trigger_summarization: bool = False
    counter_uses_fallback: bool = True


def test_task_classification_for_all_task_types():
    assert classify_retrieval_task("what is my email?") == "identity_or_preference"
    assert classify_retrieval_task("what did we decide last time?") == "episodic_recall"
    assert classify_retrieval_task("how do I deploy staging?") == "procedural_how_to"
    assert classify_retrieval_task("continue the phase 9 architecture migration") == "project_context"
    assert classify_retrieval_task("catch me up with a recap") == "summary_context"
    assert classify_retrieval_task("what should I remember about this?") == "broad_memory"


def test_ambiguous_queries_use_deterministic_priority():
    assert classify_retrieval_task("how do I use my preferred deploy workflow from last time?") == "procedural_how_to"
    assert classify_retrieval_task("what is my email from the previous conversation?") == "identity_or_preference"
    assert classify_retrieval_task("summarize what we decided last time") == "episodic_recall"


def test_memory_kind_selection_table():
    assert select_memory_kinds("identity_or_preference") == ("semantic", "summary", "episodic")
    assert select_memory_kinds("episodic_recall") == ("episodic", "summary", "semantic")
    assert select_memory_kinds("procedural_how_to") == ("procedural", "semantic", "episodic")
    assert select_memory_kinds("project_context") == ("summary", "episodic", "semantic", "procedural")
    assert select_memory_kinds("summary_context") == ("summary", "episodic", "semantic")
    assert select_memory_kinds("broad_memory") == ("semantic", "episodic", "procedural", "summary")


def test_token_allocation_sums_to_budget_and_is_deterministic():
    first = allocate_retrieval_budget("procedural_how_to", 1000)
    second = allocate_retrieval_budget("procedural_how_to", 1000)

    assert first == second
    assert sum(first.values()) == 1000
    assert set(first) == {"procedural", "semantic", "episodic"}
    assert first["procedural"] > first["semantic"]


def test_token_allocation_excludes_unselected_kinds():
    allocation = allocate_retrieval_budget("summary_context", 900, memory_kinds=("summary", "semantic"))

    assert set(allocation) == {"summary", "semantic"}
    assert sum(allocation.values()) == 900


def test_no_token_room_disables_retrieval(monkeypatch):
    monkeypatch.setattr(
        "src.memory.retrieval_planner.calculate_budget_for_primary_route",
        lambda **kwargs: FakeBudget(available_input_tokens=100, historical_conversation_tokens=90, current_user_message_tokens=10),
    )

    plan = build_retrieval_plan(
        query="what is my email",
        session_id="sess",
        provider="openai",
        model_name="gpt-4o-mini",
        messages=[HumanMessage(content="what is my email")],
        gate_allows_retrieval=True,
    )

    assert plan.should_retrieve is False
    assert plan.gate_reason == "no_token_room"
    assert plan.retrieval_request is None


def test_build_retrieval_plan_uses_gate_result_and_no_model_factories(monkeypatch):
    def fail_factory(*args, **kwargs):
        raise AssertionError("model factory should not be called")

    monkeypatch.setattr("src.harness.models.get_model_instance", fail_factory)
    monkeypatch.setattr("src.memory.retrieval_planner.calculate_budget_for_primary_route", lambda **kwargs: FakeBudget())

    skipped = build_retrieval_plan(
        query="what is my email",
        session_id="sess",
        provider="openai",
        model_name="gpt-4o-mini",
        messages=[HumanMessage(content="what is my email")],
        gate_allows_retrieval=False,
    )
    planned = build_retrieval_plan(
        query="what is my email",
        session_id="sess",
        provider="openai",
        model_name="gpt-4o-mini",
        messages=[HumanMessage(content="what is my email")],
        gate_allows_retrieval=True,
    )

    assert skipped.should_retrieve is False
    assert planned.should_retrieve is True
    assert planned.retrieval_request.memory_kinds == ("semantic", "summary", "episodic")
