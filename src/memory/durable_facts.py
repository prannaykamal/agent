"""Promote high-confidence durable facts from background extraction.

Chat stays regex-only. The worker LLM may infer lasting facts from meaning;
only those facts are written to permanent memory.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from src.memory.semantic_store import SemanticFactStore, SemanticFactWrite


DURABLE_MIN_CONFIDENCE = 0.75
ALLOWED_CATEGORIES = {
    "user_fact",
    "user_profile",
    "user_preference",
    "profile",
    "preference",
    "general",
}
CATEGORY_ALIASES = {
    "preference": "user_preference",
    "profile": "user_profile",
    "contact": "user_fact",
    "user_contact": "user_fact",
    "general": "user_fact",
}
_EPHEMERAL_PREFIX = re.compile(
    r"^(?:(?:the\s+)?user\s+)?(?:wants to |asked to |requested to )?(?:send|draft|create|schedule|search|find|look up|email|mail|remind)\b",
    flags=re.IGNORECASE,
)

DURABLE_FACT_PROMPT = """Extract lasting personal facts from this completed chat turn.

Return only JSON:
{"candidates":[{"fact":"...","category":"user_fact|user_profile|user_preference","confidence":0.0,"durable":true,"rationale":"..."}]}

Rules:
- durable=true only if the fact should still be true in a later chat: identity, preferences, named people or places, roles, constraints, contact details, tools the user uses.
- durable=false for greetings, one-off tasks, "send/draft this message", and guesses.
- Do not invent details that the user did not state.
- If nothing is worth remembering, return {"candidates":[]}.
"""


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in {0, 1}:
        return bool(value)
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def normalize_fact_category(category: Any) -> str:
    raw = " ".join(str(category or "user_fact").split()).lower()
    if not raw:
        return "user_fact"
    return CATEGORY_ALIASES.get(raw, raw)


def is_ephemeral_fact(fact_text: str) -> bool:
    cleaned = " ".join(str(fact_text or "").split())
    if not cleaned or "?" in cleaned:
        return True
    return bool(_EPHEMERAL_PREFIX.search(cleaned))


def should_promote_durable_fact(
    *,
    fact_text: str,
    category: str = "user_fact",
    confidence: float = 0.0,
    durable: Any = False,
) -> bool:
    if not as_bool(durable):
        return False
    try:
        parsed_confidence = float(confidence)
    except (TypeError, ValueError):
        return False
    if parsed_confidence < DURABLE_MIN_CONFIDENCE:
        return False
    if is_ephemeral_fact(fact_text):
        return False
    normalized_category = normalize_fact_category(category)
    if normalized_category not in ALLOWED_CATEGORIES and normalized_category not in CATEGORY_ALIASES.values():
        return False
    return True


def candidate_is_durable(candidate: Any) -> bool:
    metadata = getattr(candidate, "metadata", None) or {}
    if not isinstance(metadata, Mapping):
        metadata = {}
    return should_promote_durable_fact(
        fact_text=str(getattr(candidate, "fact", "") or getattr(candidate, "fact_text", "")),
        category=str(getattr(candidate, "category", "user_fact") or "user_fact"),
        confidence=float(getattr(candidate, "confidence", 0.0) or 0.0),
        durable=metadata.get("durable"),
    )


def promote_durable_candidates(
    candidates: Sequence[Any],
    *,
    db_path: Optional[Path] = None,
    memory_path: Optional[Path] = None,
) -> int:
    """Write durable worker-extracted facts through the dedup-aware store."""
    from src.memory.semantic_candidates import PendingFactCandidateStore

    store = SemanticFactStore(db_path=db_path, memory_path=memory_path)
    pending_store = PendingFactCandidateStore(db_path=db_path)
    promoted = 0
    for candidate in candidates:
        if not candidate_is_durable(candidate):
            continue
        fact_text = str(getattr(candidate, "fact", "") or getattr(candidate, "fact_text", "")).strip()
        if not fact_text:
            continue
        try:
            record = store.add_explicit_fact(
                SemanticFactWrite(
                    category=normalize_fact_category(getattr(candidate, "category", "user_fact")),
                    fact_text=fact_text,
                    source="secondary_llm_durable",
                    confidence=min(1.0, max(float(getattr(candidate, "confidence", 0.0) or 0.0), DURABLE_MIN_CONFIDENCE)),
                    explicit=True,
                )
            )
        except Exception:
            continue
        candidate_id = str(getattr(candidate, "id", "") or "")
        if candidate_id:
            try:
                pending_store.update_status(
                    candidate_id,
                    "PROMOTED",
                    processed=True,
                    metadata_update={"promoted_fact_id": str(record.id), "promotion_source": "durable_llm"},
                )
            except Exception:
                pass
        promoted += 1
    return promoted


def durable_flag_from_mapping(candidate: Mapping[str, Any]) -> bool:
    for key in ("durable", "should_remember", "important", "long_term"):
        if key in candidate:
            return as_bool(candidate.get(key))
    return False
