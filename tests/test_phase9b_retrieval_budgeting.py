from dataclasses import dataclass

from langchain_core.messages import HumanMessage, AIMessage

from src.memory.retrieval_planner import build_retrieval_plan


@dataclass(frozen=True)
class FakeBudget:
    provider: str = "openai"
    model_name: str = "gpt-4o-mini"
    context_window: int = 128000
    conversation_budget_tokens: int = 96000
    summarization_trigger_tokens: int = 86400
    historical_conversation_tokens: int = 1000
    current_user_message_tokens: int = 100
    system_prompt_tokens: int = 0
    tool_schema_tokens: int = 0
    retrieved_memory_tokens: int = 0
    output_reserve_tokens: int = 12800
    safety_margin_tokens: int = 6400
    reserved_tokens: int = 19200
    available_input_tokens: int = 108800
    budget_usage_ratio: float = 0.01
    trigger_usage_ratio: float = 0.01
    should_trigger_summarization: bool = False
    counter_uses_fallback: bool = True


def test_large_context_window_caps_retrieval_budget_at_4096(monkeypatch):
    monkeypatch.setattr("src.memory.retrieval_planner.calculate_budget_for_primary_route", lambda **kwargs: FakeBudget())

    plan = build_retrieval_plan(
        query="what do you know about my project",
        session_id="sess",
        provider="openai",
        model_name="gpt-4o-mini",
        messages=[HumanMessage(content="what do you know about my project")],
        gate_allows_retrieval=True,
    )

    assert plan.total_token_budget == 4096
    assert sum(plan.budget_by_kind.values()) == 4096


def test_small_context_window_does_not_exceed_available_room(monkeypatch):
    monkeypatch.setattr(
        "src.memory.retrieval_planner.calculate_budget_for_primary_route",
        lambda **kwargs: FakeBudget(
            context_window=4000,
            available_input_tokens=1500,
            historical_conversation_tokens=1200,
            current_user_message_tokens=100,
        ),
    )

    plan = build_retrieval_plan(
        query="what did we decide last time",
        session_id="sess",
        provider="openai",
        model_name="gpt-4o-mini",
        messages=[HumanMessage(content="what did we decide last time")],
        gate_allows_retrieval=True,
    )

    assert plan.total_token_budget == 200
    assert sum(plan.budget_by_kind.values()) == 200


def test_budget_uses_current_messages_without_mutating_them(monkeypatch):
    monkeypatch.setattr("src.memory.retrieval_planner.calculate_budget_for_primary_route", lambda **kwargs: FakeBudget())
    messages = [HumanMessage(content="first"), AIMessage(content="second"), HumanMessage(content="what is my email")]

    build_retrieval_plan(
        query="what is my email",
        session_id="sess",
        provider="openai",
        model_name="gpt-4o-mini",
        messages=messages,
        gate_allows_retrieval=True,
    )

    assert [message.content for message in messages] == ["first", "second", "what is my email"]
