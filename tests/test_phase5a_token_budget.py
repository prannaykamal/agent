from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from src.memory.config import ShortTermMemoryConfig
from src.memory.token_budget import (
    FallbackTokenCounter,
    ProviderAwareTokenCounter,
    TokenBudgetInputs,
    calculate_budget_for_primary_route,
    calculate_conversation_token_budget,
    calculate_message_token_breakdown,
    split_historical_and_current_user_messages,
)


def _test_config() -> ShortTermMemoryConfig:
    return ShortTermMemoryConfig(
        conversation_budget_ratio=0.75,
        summarization_trigger_ratio=0.90,
        output_reserve_ratio=0.10,
        safety_margin_ratio=0.05,
        max_summary_blocks=20,
    )


def test_fallback_counter_empty_text_and_messages_return_zero():
    counter = FallbackTokenCounter()

    assert counter.count_text("", "gpt-4o-mini") == 0
    assert counter.count_messages([], "gpt-4o-mini") == 0


def test_fallback_counter_preserves_legacy_len_content_divided_by_four():
    messages = [
        HumanMessage(content="abcdefgh"),
        AIMessage(content="abcdefghijkl"),
        SystemMessage(content="abcd"),
    ]

    assert FallbackTokenCounter().count_messages(messages, "gpt-4o-mini") == 6


def test_provider_aware_counter_is_deterministic_and_uses_fallback():
    counter = ProviderAwareTokenCounter()
    messages = [HumanMessage(content="abcdefghijklmnop")]

    assert counter.count_messages(messages, "gpt-4o-mini", provider="openai") == 4
    assert counter.count_messages(messages, "gpt-4o-mini", provider="anthropic") == 4

    selector = counter.selector_for("xai", "grok-2-latest")
    assert selector.provider == "grok"
    assert selector.tokenizer_name == "fallback:grok"
    assert selector.uses_fallback is True


def test_context_window_resolution_uses_primary_selector():
    openai_budget = calculate_budget_for_primary_route(
        provider="openai",
        model_name="gpt-4o",
        messages=[],
        config=_test_config(),
    )
    anthropic_budget = calculate_budget_for_primary_route(
        provider="anthropic",
        model_name="Claude Opus 4.1",
        messages=[],
        config=_test_config(),
    )
    gemini_budget = calculate_budget_for_primary_route(
        provider="gemini",
        model_name="Gemini 2.5 Pro",
        messages=[],
        config=_test_config(),
    )
    grok_budget = calculate_budget_for_primary_route(
        provider="xai",
        model_name="grok-2-latest",
        messages=[],
        config=_test_config(),
    )

    assert openai_budget.context_window == 128000
    assert anthropic_budget.context_window == 200000
    assert gemini_budget.context_window == 1000000
    assert grok_budget.provider == "grok"
    assert grok_budget.context_window == 128000


def test_unknown_provider_falls_back_to_openai_selector():
    budget = calculate_budget_for_primary_route(
        provider="not-real",
        model_name=None,
        messages=[],
        config=_test_config(),
    )

    assert budget.provider == "openai"
    assert budget.model_name == "gpt-4o"
    assert budget.context_window == 128000


def test_latest_human_message_is_excluded_and_reported_separately():
    messages = [
        SystemMessage(content="abcd"),
        HumanMessage(content="abcdefgh"),
        AIMessage(content="abcdefghijkl"),
        HumanMessage(content="abcdefghijklmnop"),
    ]

    historical, current = split_historical_and_current_user_messages(messages)
    breakdown = calculate_message_token_breakdown(
        messages,
        provider="openai",
        model_name="gpt-4o-mini",
    )

    assert historical == messages[:3]
    assert current == messages[-1]
    assert breakdown.system_tokens == 1
    assert breakdown.historical_conversation_tokens == 5
    assert breakdown.current_user_message_tokens == 4
    assert breakdown.historical_message_count == 2
    assert breakdown.current_user_message_present is True


def test_tool_messages_count_as_historical_conversation_tokens():
    messages = [
        HumanMessage(content="abcdefgh"),
        AIMessage(content="abcdefghijkl"),
        ToolMessage(content="abcdefghijklmnop", tool_call_id="call_1"),
        HumanMessage(content="current user message"),
    ]

    breakdown = calculate_message_token_breakdown(
        messages,
        provider="openai",
        model_name="gpt-4o-mini",
    )

    assert breakdown.historical_conversation_tokens == 9
    assert breakdown.tool_message_tokens == 4


def test_reserve_accounting_reduces_conversation_budget():
    budget = calculate_conversation_token_budget(
        TokenBudgetInputs(
            provider="openai",
            model_name="gpt-4o-mini",
            messages=[],
            system_prompt_tokens=100,
            tool_schema_tokens=200,
            retrieved_memory_tokens=50,
            output_reserve_tokens=100,
            safety_margin_tokens=50,
        ),
        context_window=1000,
        config=_test_config(),
    )

    assert budget.system_prompt_tokens == 100
    assert budget.tool_schema_tokens == 200
    assert budget.retrieved_memory_tokens == 50
    assert budget.output_reserve_tokens == 100
    assert budget.safety_margin_tokens == 50
    assert budget.reserved_tokens == 500
    assert budget.conversation_budget_tokens == 500


def test_text_reserves_are_counted_when_precomputed_tokens_are_not_supplied():
    budget = calculate_conversation_token_budget(
        TokenBudgetInputs(
            provider="openai",
            model_name="gpt-4o-mini",
            messages=[SystemMessage(content="abcd")],
            system_prompt_text="abcdefgh",
            tool_schema_texts=("abcdefghijkl",),
            retrieved_memory_texts=("abcdefghijklmnop",),
            output_reserve_tokens=100,
            safety_margin_tokens=50,
        ),
        context_window=1000,
        config=_test_config(),
    )

    assert budget.system_prompt_tokens == 3
    assert budget.tool_schema_tokens == 3
    assert budget.retrieved_memory_tokens == 4
    assert budget.reserved_tokens == 160


def test_default_conversation_budget_is_capped_at_seventy_five_percent():
    budget = calculate_conversation_token_budget(
        TokenBudgetInputs(
            provider="openai",
            model_name="gpt-4o-mini",
            messages=[],
        ),
        context_window=1000,
        config=_test_config(),
    )

    assert budget.output_reserve_tokens == 100
    assert budget.safety_margin_tokens == 50
    assert budget.conversation_budget_tokens == 750


def test_summarization_trigger_is_ninety_percent_of_budget():
    budget = calculate_conversation_token_budget(
        TokenBudgetInputs(
            provider="openai",
            model_name="gpt-4o-mini",
            messages=[],
        ),
        context_window=1000,
        config=_test_config(),
    )

    assert budget.summarization_trigger_tokens == 675


def test_trigger_diagnostic_false_below_threshold_and_true_at_threshold():
    below = calculate_conversation_token_budget(
        TokenBudgetInputs(
            provider="openai",
            model_name="gpt-4o-mini",
            messages=[AIMessage(content="a" * 674 * 4), HumanMessage(content="current")],
        ),
        context_window=1000,
        config=_test_config(),
    )
    at_threshold = calculate_conversation_token_budget(
        TokenBudgetInputs(
            provider="openai",
            model_name="gpt-4o-mini",
            messages=[AIMessage(content="a" * 675 * 4), HumanMessage(content="current")],
        ),
        context_window=1000,
        config=_test_config(),
    )

    assert below.historical_conversation_tokens == 674
    assert below.should_trigger_summarization is False
    assert at_threshold.historical_conversation_tokens == 675
    assert at_threshold.should_trigger_summarization is True


def test_huge_reserves_clamp_budget_to_zero():
    budget = calculate_conversation_token_budget(
        TokenBudgetInputs(
            provider="openai",
            model_name="gpt-4o-mini",
            messages=[AIMessage(content="a" * 100)],
            system_prompt_tokens=1000,
            tool_schema_tokens=1000,
            retrieved_memory_tokens=1000,
            output_reserve_tokens=1000,
            safety_margin_tokens=1000,
        ),
        context_window=1000,
        config=_test_config(),
    )

    assert budget.conversation_budget_tokens == 0
    assert budget.summarization_trigger_tokens == 0
    assert budget.should_trigger_summarization is False
    assert budget.budget_usage_ratio == 1.0


def test_input_messages_are_not_mutated():
    messages = [
        HumanMessage(content="old user"),
        AIMessage(content="assistant"),
        HumanMessage(content="current user"),
    ]
    original_ids = [id(message) for message in messages]
    original_contents = [message.content for message in messages]

    calculate_budget_for_primary_route(
        provider="openai",
        model_name="gpt-4o-mini",
        messages=messages,
        config=_test_config(),
    )

    assert [id(message) for message in messages] == original_ids
    assert [message.content for message in messages] == original_contents


def test_budget_helpers_do_not_call_llm_factories_or_invoke(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("budget primitives must not instantiate or invoke LLMs")

    monkeypatch.setattr("src.harness.llm_router.resolve_primary_llm", fail)
    monkeypatch.setattr("src.harness.llm_router.resolve_secondary_llm", fail)
    monkeypatch.setattr("src.harness.models.get_primary_llm", fail)
    monkeypatch.setattr("src.harness.models.get_secondary_llm", fail)
    monkeypatch.setattr("src.harness.models.get_model_instance", fail)

    budget = calculate_budget_for_primary_route(
        provider="openai",
        model_name="gpt-4o-mini",
        messages=[HumanMessage(content="current")],
        config=_test_config(),
    )

    assert budget.context_window == 128000
    assert budget.current_user_message_tokens == 1

