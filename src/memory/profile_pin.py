"""Compact always-on identity profile. Read-only; never writes."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence, Tuple

from src.memory.fact_keys import keep_newest_per_attribute_key
from src.memory.retrieval_sources import IDENTITY_FACT_CATEGORIES
from src.memory.semantic_store import SemanticFactRecord, SemanticFactStore


PINNED_PROFILE_HEADER = "[Pinned Long-Term Profile]"
MAX_PROFILE_TOKENS = 600
MAX_PROFILE_LINES = 12
MIN_PROFILE_CONFIDENCE = 0.75


def _token_count(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


def select_pinned_facts(facts: Sequence[SemanticFactRecord]) -> Tuple[SemanticFactRecord, ...]:
    eligible = [
        fact
        for fact in facts
        if str(fact.category or "").lower() in IDENTITY_FACT_CATEGORIES
        and float(fact.confidence or 0.0) >= MIN_PROFILE_CONFIDENCE
        and str(fact.fact_text or "").strip()
    ]
    current = keep_newest_per_attribute_key(
        eligible,
        text_of=lambda fact: fact.fact_text,
        created_at_of=lambda fact: fact.created_at,
        confidence_of=lambda fact: fact.confidence,
        id_of=lambda fact: fact.id,
    )
    ranked = sorted(
        current,
        key=lambda fact: (str(fact.created_at or ""), int(fact.id)),
        reverse=True,
    )
    selected = []
    used_tokens = _token_count(PINNED_PROFILE_HEADER + "\n")
    for fact in ranked:
        line = f"- [{fact.category}] {fact.fact_text.strip()}"
        line_tokens = _token_count(line)
        if len(selected) >= MAX_PROFILE_LINES or used_tokens + line_tokens > MAX_PROFILE_TOKENS:
            break
        selected.append(fact)
        used_tokens += line_tokens
    return tuple(selected)


def format_pinned_profile(facts: Sequence[SemanticFactRecord]) -> str:
    selected = select_pinned_facts(facts)
    if not selected:
        return ""
    lines = [PINNED_PROFILE_HEADER]
    for fact in selected:
        lines.append(f"- [{fact.category}] {fact.fact_text.strip()}")
    return "\n".join(lines)


def assemble_pinned_profile(*, db_path: Optional[Path] = None) -> str:
    facts = SemanticFactStore(db_path=db_path).list_facts()
    return format_pinned_profile(facts)
