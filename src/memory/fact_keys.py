"""Read-only (entity, attribute) keys so retrieve and pin keep one current value."""

from __future__ import annotations

import re
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple, TypeVar

from src.memory.retrieval_ranker import _parse_datetime, tokenize_retrieval_text


T = TypeVar("T")

_POSSESSIVE_FACT = re.compile(
    r"\b([A-Za-z][A-Za-z0-9.\-]{1,40}(?:\s+[A-Za-z][A-Za-z0-9.\-]{1,40}){0,2})['’]s\s+"
    r"([A-Za-z][A-Za-z0-9 \-]{0,40}?)\s+(?:is|:)\s+",
    flags=re.IGNORECASE,
)
_ATTRIBUTE_OF_ENTITY = re.compile(
    r"\b(?:the\s+)?([A-Za-z][A-Za-z0-9 \-]{1,40}?)\s+(?:of|for)\s+"
    r"([A-Za-z][A-Za-z0-9.\-]{1,40}(?:\s+[A-Za-z][A-Za-z0-9.\-]{1,40}){0,2})\s+"
    r"(?:is|:)\s+",
    flags=re.IGNORECASE,
)
_MY_ATTRIBUTE = re.compile(
    r"\bmy\s+([A-Za-z][A-Za-z0-9 \-]{0,40}?)\s+(?:is|:)\s+",
    flags=re.IGNORECASE,
)
_ENTITY_IS_MY = re.compile(
    r"\b([A-Za-z][A-Za-z0-9.\-]{1,40}(?:\s+[A-Za-z][A-Za-z0-9.\-]{1,40}){0,2})\s+"
    r"is\s+my\s+([A-Za-z][A-Za-z0-9 \-]{1,40}?)"
    r"(?:[.!?](?:\s|$)|$)",
    flags=re.IGNORECASE,
)
_ENTITY_IS_USER = re.compile(
    r"\b([A-Za-z][A-Za-z0-9.\-]{1,40}(?:\s+[A-Za-z][A-Za-z0-9.\-]{1,40}){0,2})\s+"
    r"is\s+(?:the\s+)?user(?:'s)?\s+([A-Za-z][A-Za-z0-9 \-]{1,40}?)"
    r"(?:[.!?](?:\s|$)|$)",
    flags=re.IGNORECASE,
)
_LOCATION = re.compile(
    r"\b(?:the\s+)?([A-Za-z][A-Za-z0-9.\-]{1,40}(?:\s+[A-Za-z][A-Za-z0-9.\-]{1,40}){0,2})\s+"
    r"(?:is\s+(?:in|at)|lives?\s+in|moved\s+to|located\s+in)\s+",
    flags=re.IGNORECASE,
)

_ENTITY_STOP = {
    "a", "an", "the", "my", "his", "her", "their", "our", "your", "me", "him", "them",
    "this", "that", "these", "those", "it", "please", "remember", "forget",
    "i", "we", "you", "they", "who", "what", "when", "where", "why", "how",
    "there", "here", "someone", "anyone",
}
_ATTRIBUTE_STOP = {
    "reason", "purpose", "point", "thing", "way", "one", "idea", "issue", "problem",
    "question", "case", "kind", "sort", "type", "guess", "feeling", "thought",
    "impression", "take", "view", "fault", "bad", "good", "sense",
}


def _clean(value: str) -> str:
    return " ".join(str(value or "").split()).strip(" .!?,;:")


def _norm_entity(value: str) -> str:
    cleaned = re.sub(r"['’]s$", "", _clean(value), flags=re.IGNORECASE)
    return " ".join(cleaned.lower().split())


def _norm_attribute(value: str) -> str:
    return " ".join(_clean(value).lower().split())


def _valid_entity(value: str) -> bool:
    parts = [part for part in value.split() if part]
    if not parts:
        return False
    return not any(part in _ENTITY_STOP for part in parts)


def _valid_attribute(value: str) -> bool:
    if not value or len(value.split()) > 4:
        return False
    return value not in _ATTRIBUTE_STOP


def fact_attribute_key(text: str) -> Optional[Tuple[str, str]]:
    """Return a stable (entity, attribute) key, ignoring the current value."""
    raw = str(text or "").strip()
    if not raw:
        return None

    match = _POSSESSIVE_FACT.search(raw)
    if match:
        entity = _norm_entity(match.group(1))
        attribute = _norm_attribute(match.group(2))
        if _valid_entity(entity) and _valid_attribute(attribute):
            return (entity, attribute)

    match = _ATTRIBUTE_OF_ENTITY.search(raw)
    if match:
        attribute = _norm_attribute(match.group(1))
        entity = _norm_entity(match.group(2))
        if _valid_entity(entity) and _valid_attribute(attribute):
            return (entity, attribute)

    match = _MY_ATTRIBUTE.search(raw)
    if match:
        attribute = _norm_attribute(match.group(1))
        if _valid_attribute(attribute):
            return ("user", attribute)

    match = _ENTITY_IS_MY.search(raw)
    if match:
        entity = _norm_entity(match.group(1))
        attribute = _norm_attribute(match.group(2))
        if _valid_entity(entity) and _valid_attribute(attribute):
            return (entity, attribute)

    match = _ENTITY_IS_USER.search(raw)
    if match:
        entity = _norm_entity(match.group(1))
        attribute = _norm_attribute(match.group(2))
        if _valid_entity(entity) and _valid_attribute(attribute):
            return (entity, attribute)

    match = _LOCATION.search(raw)
    if match:
        entity = _norm_entity(match.group(1))
        if _valid_entity(entity):
            return (entity, "location")

    tokens = tokenize_retrieval_text(raw)
    if not tokens:
        return None
    entity = tokens[0]
    attribute = next((token for token in tokens[1:] if len(token) >= 3), None)
    if not attribute:
        return (entity, "fact")
    return (entity, attribute)


def attribute_dedupe_key(text: str, *, fallback_id: object) -> Tuple[str, str]:
    parsed = fact_attribute_key(text)
    if parsed is not None:
        return parsed
    return ("id", str(fallback_id))


def _sort_tuple(created_at: object, confidence: object, record_id: object) -> Tuple[float, float, int, str]:
    parsed = _parse_datetime(str(created_at) if created_at is not None else None)
    timestamp = parsed.timestamp() if parsed is not None else 0.0
    try:
        conf = float(confidence or 0.0)
    except (TypeError, ValueError):
        conf = 0.0
    raw_id = str(record_id or "")
    try:
        numeric_id = int(raw_id)
    except (TypeError, ValueError):
        numeric_id = 0
    return (timestamp, conf, numeric_id, raw_id)


def keep_newest_per_attribute_key(
    items: Sequence[T],
    *,
    text_of: Callable[[T], str],
    created_at_of: Callable[[T], object],
    confidence_of: Callable[[T], object],
    id_of: Callable[[T], object],
) -> List[T]:
    """Keep the newest item per (entity, attribute). Does not delete anything."""
    winners: Dict[Tuple[str, str], T] = {}
    winner_sort: Dict[Tuple[str, str], Tuple[float, float, int, str]] = {}
    for item in items:
        key = attribute_dedupe_key(text_of(item), fallback_id=id_of(item))
        sort_key = _sort_tuple(created_at_of(item), confidence_of(item), id_of(item))
        current = winner_sort.get(key)
        if current is None or sort_key > current:
            winners[key] = item
            winner_sort[key] = sort_key
    winner_ids = {id(item) for item in winners.values()}
    return [item for item in items if id(item) in winner_ids]


def keep_newest_semantic_candidates(candidates: Iterable[T]) -> List[T]:
    items = list(candidates)
    if not items:
        return []
    return keep_newest_per_attribute_key(
        items,
        text_of=lambda candidate: str(getattr(candidate, "content", "") or ""),
        created_at_of=lambda candidate: getattr(getattr(candidate, "provenance", None), "created_at", None),
        confidence_of=lambda candidate: (getattr(getattr(candidate, "provenance", None), "metadata", None) or {}).get(
            "confidence", 0.0
        ),
        id_of=lambda candidate: getattr(getattr(candidate, "provenance", None), "record_id", None)
        or getattr(candidate, "id", ""),
    )
