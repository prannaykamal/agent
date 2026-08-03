from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage

from src.memory.config import ShortTermMemoryConfig, load_memory_config


@dataclass(frozen=True)
class TokenCounterSelector:
    provider: str
    model_name: str
    tokenizer_name: str
    uses_fallback: bool


@dataclass(frozen=True)
class MessageTokenBreakdown:
    system_tokens: int
    historical_conversation_tokens: int
    current_user_message_tokens: int
    tool_message_tokens: int
    total_counted_tokens: int
    historical_message_count: int
    current_user_message_present: bool


@dataclass(frozen=True)
class TokenBudgetInputs:
    provider: Optional[str]
    model_name: Optional[str]
    messages: Sequence[BaseMessage]
    system_prompt_text: str = ""
    tool_schema_texts: Sequence[str] = ()
    retrieved_memory_texts: Sequence[str] = ()
    output_reserve_tokens: Optional[int] = None
    safety_margin_tokens: Optional[int] = None
    exclude_current_user_message: bool = True
    system_prompt_tokens: Optional[int] = None
    tool_schema_tokens: Optional[int] = None
    retrieved_memory_tokens: Optional[int] = None


@dataclass(frozen=True)
class ConversationTokenBudget:
    provider: str
    model_name: str
    context_window: int
    conversation_budget_tokens: int
    summarization_trigger_tokens: int
    historical_conversation_tokens: int
    current_user_message_tokens: int
    system_prompt_tokens: int
    tool_schema_tokens: int
    retrieved_memory_tokens: int
    output_reserve_tokens: int
    safety_margin_tokens: int
    reserved_tokens: int
    available_input_tokens: int
    budget_usage_ratio: float
    trigger_usage_ratio: float
    should_trigger_summarization: bool
    counter_uses_fallback: bool


class FallbackTokenCounter:
    """Deterministic legacy-compatible character heuristic."""

    def count_text(self, text: str, model_name: str) -> int:
        if not text:
            return 0
        return len(str(text)) // 4

    def count_messages(self, messages: Sequence[BaseMessage], model_name: str) -> int:
        if not messages:
            return 0
        total_chars = sum(len(str(message.content)) for message in messages)
        return total_chars // 4


class ProviderAwareTokenCounter:
    def __init__(self, fallback: Optional[FallbackTokenCounter] = None):
        self.fallback = fallback if fallback is not None else FallbackTokenCounter()

    def selector_for(self, provider: str, model_name: str) -> TokenCounterSelector:
        from src.harness.llm_router import normalize_provider

        normalized_provider = normalize_provider(provider)
        return TokenCounterSelector(
            provider=normalized_provider,
            model_name=model_name,
            tokenizer_name=f"fallback:{normalized_provider}",
            uses_fallback=True,
        )

    def count_text(self, text: str, model_name: str, provider: str = "openai") -> int:
        return self.fallback.count_text(text, model_name)

    def count_messages(
        self,
        messages: Sequence[BaseMessage],
        model_name: str,
        provider: str = "openai",
    ) -> int:
        return self.fallback.count_messages(messages, model_name)


def get_token_counter(
    provider: Optional[str] = None,
    model_name: Optional[str] = None,
) -> ProviderAwareTokenCounter:
    return ProviderAwareTokenCounter()


def split_historical_and_current_user_messages(
    messages: Sequence[BaseMessage],
    exclude_current_user_message: bool = True,
) -> Tuple[list[BaseMessage], Optional[HumanMessage]]:
    message_list = list(messages or [])
    latest_user_index: Optional[int] = None
    latest_user_message: Optional[HumanMessage] = None

    for index in range(len(message_list) - 1, -1, -1):
        message = message_list[index]
        if isinstance(message, HumanMessage):
            latest_user_index = index
            latest_user_message = message
            break

    if exclude_current_user_message and latest_user_index is not None:
        historical = message_list[:latest_user_index] + message_list[latest_user_index + 1 :]
    else:
        historical = list(message_list)

    return historical, latest_user_message


def count_message_tokens(
    messages: Sequence[BaseMessage],
    provider: str = "openai",
    model_name: str = "gpt-4o-mini",
    counter: Optional[ProviderAwareTokenCounter] = None,
) -> int:
    token_counter = counter if counter is not None else get_token_counter(provider, model_name)
    return token_counter.count_messages(messages, model_name=model_name, provider=provider)


def _count_texts(
    texts: Sequence[str],
    provider: str,
    model_name: str,
    counter: ProviderAwareTokenCounter,
) -> int:
    if not texts:
        return 0
    return counter.count_text("".join(str(text) for text in texts), model_name=model_name, provider=provider)


def _coerce_token_count(value: Optional[int]) -> Optional[int]:
    if value is None:
        return None
    return max(0, int(value))


def calculate_message_token_breakdown(
    messages: Sequence[BaseMessage],
    provider: str = "openai",
    model_name: str = "gpt-4o-mini",
    counter: Optional[ProviderAwareTokenCounter] = None,
    exclude_current_user_message: bool = True,
) -> MessageTokenBreakdown:
    token_counter = counter if counter is not None else get_token_counter(provider, model_name)
    historical_messages, current_user_message = split_historical_and_current_user_messages(
        messages,
        exclude_current_user_message=exclude_current_user_message,
    )
    system_messages = [message for message in historical_messages if isinstance(message, SystemMessage)]
    conversation_messages = [
        message for message in historical_messages if not isinstance(message, SystemMessage)
    ]
    tool_messages = [message for message in conversation_messages if isinstance(message, ToolMessage)]

    system_tokens = token_counter.count_messages(system_messages, model_name=model_name, provider=provider)
    historical_tokens = token_counter.count_messages(
        conversation_messages,
        model_name=model_name,
        provider=provider,
    )
    current_user_tokens = (
        token_counter.count_messages([current_user_message], model_name=model_name, provider=provider)
        if current_user_message is not None
        else 0
    )
    tool_tokens = token_counter.count_messages(tool_messages, model_name=model_name, provider=provider)

    return MessageTokenBreakdown(
        system_tokens=system_tokens,
        historical_conversation_tokens=historical_tokens,
        current_user_message_tokens=current_user_tokens,
        tool_message_tokens=tool_tokens,
        total_counted_tokens=system_tokens + historical_tokens + current_user_tokens,
        historical_message_count=len(conversation_messages),
        current_user_message_present=current_user_message is not None,
    )


def _resolve_config(config: Optional[ShortTermMemoryConfig]) -> ShortTermMemoryConfig:
    return config if config is not None else load_memory_config().short_term


def calculate_conversation_token_budget(
    inputs: TokenBudgetInputs,
    context_window: int,
    config: Optional[ShortTermMemoryConfig] = None,
    counter: Optional[ProviderAwareTokenCounter] = None,
) -> ConversationTokenBudget:
    resolved_config = _resolve_config(config)
    provider = inputs.provider or "openai"
    model_name = inputs.model_name or "gpt-4o-mini"
    token_counter = counter if counter is not None else get_token_counter(provider, model_name)
    selector = token_counter.selector_for(provider, model_name)

    breakdown = calculate_message_token_breakdown(
        inputs.messages,
        provider=selector.provider,
        model_name=model_name,
        counter=token_counter,
        exclude_current_user_message=inputs.exclude_current_user_message,
    )

    explicit_system_tokens = _coerce_token_count(inputs.system_prompt_tokens)
    explicit_tool_tokens = _coerce_token_count(inputs.tool_schema_tokens)
    explicit_retrieved_tokens = _coerce_token_count(inputs.retrieved_memory_tokens)

    system_prompt_tokens = (
        explicit_system_tokens
        if explicit_system_tokens is not None
        else breakdown.system_tokens
        + token_counter.count_text(inputs.system_prompt_text, model_name=model_name, provider=selector.provider)
    )
    tool_schema_tokens = (
        explicit_tool_tokens
        if explicit_tool_tokens is not None
        else _count_texts(inputs.tool_schema_texts, selector.provider, model_name, token_counter)
    )
    retrieved_memory_tokens = (
        explicit_retrieved_tokens
        if explicit_retrieved_tokens is not None
        else _count_texts(inputs.retrieved_memory_texts, selector.provider, model_name, token_counter)
    )

    resolved_context_window = max(0, int(context_window))
    output_reserve_tokens = _coerce_token_count(inputs.output_reserve_tokens)
    if output_reserve_tokens is None:
        output_reserve_tokens = int(resolved_context_window * resolved_config.output_reserve_ratio)

    safety_margin_tokens = _coerce_token_count(inputs.safety_margin_tokens)
    if safety_margin_tokens is None:
        safety_margin_tokens = int(resolved_context_window * resolved_config.safety_margin_ratio)

    reserved_tokens = (
        system_prompt_tokens
        + tool_schema_tokens
        + retrieved_memory_tokens
        + output_reserve_tokens
        + safety_margin_tokens
    )
    target_conversation_ceiling = int(
        resolved_context_window * resolved_config.conversation_budget_ratio
    )
    absolute_available_for_conversation = max(0, resolved_context_window - reserved_tokens)
    conversation_budget_tokens = max(
        0,
        min(target_conversation_ceiling, absolute_available_for_conversation),
    )
    summarization_trigger_tokens = int(
        conversation_budget_tokens * resolved_config.summarization_trigger_ratio
    )

    historical_tokens = breakdown.historical_conversation_tokens
    budget_usage_ratio = (
        historical_tokens / conversation_budget_tokens if conversation_budget_tokens > 0 else 1.0
    )
    trigger_usage_ratio = (
        historical_tokens / summarization_trigger_tokens
        if summarization_trigger_tokens > 0
        else 1.0
    )
    should_trigger_summarization = (
        summarization_trigger_tokens > 0 and historical_tokens >= summarization_trigger_tokens
    )

    return ConversationTokenBudget(
        provider=selector.provider,
        model_name=model_name,
        context_window=resolved_context_window,
        conversation_budget_tokens=conversation_budget_tokens,
        summarization_trigger_tokens=summarization_trigger_tokens,
        historical_conversation_tokens=historical_tokens,
        current_user_message_tokens=breakdown.current_user_message_tokens,
        system_prompt_tokens=system_prompt_tokens,
        tool_schema_tokens=tool_schema_tokens,
        retrieved_memory_tokens=retrieved_memory_tokens,
        output_reserve_tokens=output_reserve_tokens,
        safety_margin_tokens=safety_margin_tokens,
        reserved_tokens=reserved_tokens,
        available_input_tokens=max(0, resolved_context_window - output_reserve_tokens - safety_margin_tokens),
        budget_usage_ratio=budget_usage_ratio,
        trigger_usage_ratio=trigger_usage_ratio,
        should_trigger_summarization=should_trigger_summarization,
        counter_uses_fallback=selector.uses_fallback,
    )


def calculate_budget_for_primary_route(
    provider: Optional[str],
    model_name: Optional[str],
    messages: Sequence[BaseMessage],
    *,
    system_prompt_text: str = "",
    tool_schema_texts: Sequence[str] = (),
    retrieved_memory_texts: Sequence[str] = (),
    config: Optional[ShortTermMemoryConfig] = None,
    counter: Optional[ProviderAwareTokenCounter] = None,
    output_reserve_tokens: Optional[int] = None,
    safety_margin_tokens: Optional[int] = None,
    system_prompt_tokens: Optional[int] = None,
    tool_schema_tokens: Optional[int] = None,
    retrieved_memory_tokens: Optional[int] = None,
) -> ConversationTokenBudget:
    from src.harness.llm_router import resolve_llm_selector

    selector = resolve_llm_selector(
        role="primary",
        provider=provider,
        model_name=model_name,
        source="token_budget",
    )
    inputs = TokenBudgetInputs(
        provider=selector.provider,
        model_name=selector.model_name,
        messages=messages,
        system_prompt_text=system_prompt_text,
        tool_schema_texts=tool_schema_texts,
        retrieved_memory_texts=retrieved_memory_texts,
        output_reserve_tokens=output_reserve_tokens,
        safety_margin_tokens=safety_margin_tokens,
        system_prompt_tokens=system_prompt_tokens,
        tool_schema_tokens=tool_schema_tokens,
        retrieved_memory_tokens=retrieved_memory_tokens,
    )
    return calculate_conversation_token_budget(
        inputs,
        context_window=selector.context_window,
        config=config,
        counter=counter,
    )

