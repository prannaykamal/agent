from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Literal, Optional, Sequence, Tuple

from langchain_core.messages import BaseMessage

from src.memory.retrieval_types import RetrievalMemoryKind, RetrievalRequest
from src.memory.token_budget import calculate_budget_for_primary_route


RetrievalTaskType = Literal[
    "identity_or_preference",
    "episodic_recall",
    "procedural_how_to",
    "project_context",
    "summary_context",
    "broad_memory",
]

TASK_PRIORITY: Tuple[RetrievalTaskType, ...] = (
    "procedural_how_to",
    "identity_or_preference",
    "episodic_recall",
    "summary_context",
    "project_context",
    "broad_memory",
)

MEMORY_KIND_POLICY: Dict[RetrievalTaskType, Tuple[RetrievalMemoryKind, ...]] = {
    "identity_or_preference": ("semantic", "summary", "episodic"),
    "episodic_recall": ("episodic", "summary", "semantic"),
    "procedural_how_to": ("procedural", "semantic", "episodic"),
    "project_context": ("summary", "episodic", "semantic", "procedural"),
    "summary_context": ("summary", "episodic", "semantic"),
    "broad_memory": ("semantic", "episodic", "procedural", "summary"),
}

BUDGET_WEIGHTS: Dict[RetrievalTaskType, Dict[RetrievalMemoryKind, float]] = {
    "identity_or_preference": {"semantic": 0.65, "episodic": 0.20, "procedural": 0.0, "summary": 0.15},
    "episodic_recall": {"semantic": 0.20, "episodic": 0.55, "procedural": 0.0, "summary": 0.25},
    "procedural_how_to": {"semantic": 0.20, "episodic": 0.15, "procedural": 0.55, "summary": 0.10},
    "project_context": {"semantic": 0.20, "episodic": 0.30, "procedural": 0.10, "summary": 0.40},
    "summary_context": {"semantic": 0.20, "episodic": 0.25, "procedural": 0.0, "summary": 0.55},
    "broad_memory": {"semantic": 0.35, "episodic": 0.25, "procedural": 0.20, "summary": 0.20},
}

TASK_PATTERNS: Dict[RetrievalTaskType, Tuple[str, ...]] = {
    "procedural_how_to": (
        r"\bhow\s+(?:do|to|should)\b",
        r"\bsteps?\b",
        r"\bprocedure\b",
        r"\bworkflow\b",
        r"\bprocess\b",
        r"\bchecklist\b",
        r"\bdeploy\b",
        r"\brun\s+(?:the\s+)?(?:process|workflow|release|deploy)",
        r"\bexecute\b",
    ),
    "identity_or_preference": (
        r"\bmy\s+name\b",
        r"\bmy\s+email\b",
        r"\bmy\s+preference\b",
        r"\bwhat\s+do\s+i\s+(?:like|prefer)\b",
        r"\bwhat\s+do\s+you\s+know\s+about\s+me\b",
        r"\bwho\s+am\s+i\b",
        r"\bremembered\s+preference\b",
    ),
    "episodic_recall": (
        r"\blast\s+time\b",
        r"\bpreviously\b",
        r"\bearlier\b",
        r"\bwhen\s+did\b",
        r"\bwhat\s+did\s+we\s+(?:decide|discuss|do)\b",
        r"\bmeeting\b",
        r"\bconversation\b",
        r"\bepisode\b",
        r"\bworked\s+on\b",
        r"\brecall\b",
    ),
    "summary_context": (
        r"\bsummar(?:y|ize)\b",
        r"\bcatch\s+me\s+up\b",
        r"\bwhere\s+are\s+we\b",
        r"\brecap\b",
        r"\bcontext\b",
    ),
    "project_context": (
        r"\bproject\b",
        r"\barchitecture\b",
        r"\bphase\b",
        r"\broadmap\b",
        r"\bimplementation\b",
        r"\bmigration\b",
        r"\bdesign\b",
        r"\bcurrent\s+code\b",
    ),
}


@dataclass(frozen=True)
class RetrievalPolicyProfile:
    task_type: RetrievalTaskType
    memory_kinds: Tuple[RetrievalMemoryKind, ...]
    per_source_limit: int
    token_budget: int
    allocation: Dict[RetrievalMemoryKind, int]
    rationale: Tuple[str, ...] = tuple()


@dataclass(frozen=True)
class RetrievalPlan:
    query: str
    session_id: Optional[str]
    provider: str
    model_name: str
    should_retrieve: bool
    gate_reason: str
    task_type: RetrievalTaskType
    memory_kinds: Tuple[RetrievalMemoryKind, ...]
    per_source_limit: int
    total_token_budget: int
    budget_by_kind: Dict[RetrievalMemoryKind, int]
    retrieval_request: Optional[RetrievalRequest]
    debug: Dict[str, Any] = field(default_factory=dict)


def _normalize_query(query: str) -> str:
    return " ".join(str(query or "").lower().split())


def _matches_any(query: str, patterns: Sequence[str]) -> bool:
    return any(re.search(pattern, query) for pattern in patterns)


def classify_retrieval_task(query: str) -> RetrievalTaskType:
    normalized = _normalize_query(query)
    if not normalized:
        return "broad_memory"
    for task_type in TASK_PRIORITY:
        if task_type == "broad_memory":
            return task_type
        if _matches_any(normalized, TASK_PATTERNS[task_type]):
            return task_type
    return "broad_memory"


def select_memory_kinds(task_type: RetrievalTaskType) -> Tuple[RetrievalMemoryKind, ...]:
    return MEMORY_KIND_POLICY.get(task_type, MEMORY_KIND_POLICY["broad_memory"])


def allocate_retrieval_budget(
    task_type: RetrievalTaskType,
    total_budget: int,
    memory_kinds: Optional[Sequence[RetrievalMemoryKind]] = None,
) -> Dict[RetrievalMemoryKind, int]:
    budget = max(0, int(total_budget))
    selected = tuple(memory_kinds or select_memory_kinds(task_type))
    if budget <= 0 or not selected:
        return {kind: 0 for kind in selected}

    weights = BUDGET_WEIGHTS.get(task_type, BUDGET_WEIGHTS["broad_memory"])
    selected_weights = {kind: max(0.0, float(weights.get(kind, 0.0))) for kind in selected}
    total_weight = sum(selected_weights.values())
    if total_weight <= 0:
        selected_weights = {kind: 1.0 for kind in selected}
        total_weight = float(len(selected))

    allocation = {kind: int(budget * (weight / total_weight)) for kind, weight in selected_weights.items()}
    minimum = min(128, budget // max(1, len(selected)))
    if minimum > 0 and budget >= minimum * len(selected):
        for kind in selected:
            allocation[kind] = max(allocation[kind], minimum)

    while sum(allocation.values()) > budget:
        for kind in reversed(selected):
            if allocation[kind] > 0 and sum(allocation.values()) > budget:
                allocation[kind] -= 1
    remaining = budget - sum(allocation.values())
    while remaining > 0:
        for kind in selected:
            if remaining <= 0:
                break
            allocation[kind] += 1
            remaining -= 1
    return allocation


def _calculate_retrieval_budget(
    *,
    provider: Optional[str],
    model_name: Optional[str],
    messages: Sequence[BaseMessage],
) -> tuple[int, Dict[str, Any]]:
    budget = calculate_budget_for_primary_route(
        provider=provider,
        model_name=model_name,
        messages=messages,
    )
    soft_target = min(max(512, int(budget.context_window * 0.08)), 4096)
    available_room = max(
        0,
        budget.available_input_tokens
        - budget.historical_conversation_tokens
        - budget.current_user_message_tokens
        - budget.retrieved_memory_tokens,
    )
    retrieval_budget = max(0, min(int(soft_target), int(available_room)))
    diagnostics = {
        "context_window": budget.context_window,
        "available_input_tokens": budget.available_input_tokens,
        "historical_conversation_tokens": budget.historical_conversation_tokens,
        "current_user_message_tokens": budget.current_user_message_tokens,
        "soft_target": int(soft_target),
        "available_room": int(available_room),
        "counter_uses_fallback": budget.counter_uses_fallback,
    }
    return retrieval_budget, diagnostics


def build_retrieval_plan(
    *,
    query: str,
    session_id: Optional[str],
    provider: Optional[str],
    model_name: Optional[str],
    messages: Sequence[BaseMessage],
    gate_allows_retrieval: bool,
    include_debug: bool = False,
) -> RetrievalPlan:
    normalized_query = " ".join(str(query or "").split())
    resolved_provider = provider or "openai"
    resolved_model = model_name or "gpt-4o-mini"
    task_type = classify_retrieval_task(normalized_query)
    memory_kinds = select_memory_kinds(task_type)

    if not gate_allows_retrieval or not normalized_query:
        return RetrievalPlan(
            query=normalized_query,
            session_id=session_id,
            provider=resolved_provider,
            model_name=resolved_model,
            should_retrieve=False,
            gate_reason="gate_skipped" if not gate_allows_retrieval else "empty_query",
            task_type=task_type,
            memory_kinds=memory_kinds,
            per_source_limit=0,
            total_token_budget=0,
            budget_by_kind={kind: 0 for kind in memory_kinds},
            retrieval_request=None,
            debug={} if not include_debug else {"gate_allows_retrieval": gate_allows_retrieval},
        )

    retrieval_budget, diagnostics = _calculate_retrieval_budget(
        provider=resolved_provider,
        model_name=resolved_model,
        messages=messages,
    )
    allocation = allocate_retrieval_budget(task_type, retrieval_budget, memory_kinds)
    should_retrieve = retrieval_budget > 0
    per_source_limit = 5 if retrieval_budget >= 1024 else 3
    request = None
    if should_retrieve:
        request = RetrievalRequest(
            query=normalized_query,
            session_id=session_id,
            memory_kinds=memory_kinds,
            per_source_limit=per_source_limit,
            token_budget=retrieval_budget,
            provider=resolved_provider,
            model_name=resolved_model,
            include_debug=include_debug,
        )

    return RetrievalPlan(
        query=normalized_query,
        session_id=session_id,
        provider=resolved_provider,
        model_name=resolved_model,
        should_retrieve=should_retrieve,
        gate_reason="ok" if should_retrieve else "no_token_room",
        task_type=task_type,
        memory_kinds=memory_kinds,
        per_source_limit=per_source_limit if should_retrieve else 0,
        total_token_budget=retrieval_budget,
        budget_by_kind=allocation,
        retrieval_request=request,
        debug={"budget": diagnostics, "task_type": task_type} if include_debug else {},
    )
