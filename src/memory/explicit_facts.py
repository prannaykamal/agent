"""Deterministic, domain-agnostic capture of durable user assertions.

Chat-path extraction must stay high-precision and LLM-free. Vague preferences
and action requests are ignored; stated attributes are persisted immediately.
"""

from __future__ import annotations

import re
from typing import List, Set

from src.memory.semantic_store import SemanticFactWrite


_SENTENCE_VALUE = r"(.+?)(?=\s+and\s+my\b|[.!?](?:\s|$)|$)"

_REMEMBER = re.compile(
    r"\b(?:please\s+remember(?:\s+that)?|remember\s+that)\s+" + _SENTENCE_VALUE,
    flags=re.IGNORECASE,
)
_DO_NOT_FORGET = re.compile(
    r"\b(?:do\s+not|don't)\s+forget(?:\s+that)?\s+" + _SENTENCE_VALUE,
    flags=re.IGNORECASE,
)
_POSSESSIVE_FACT = re.compile(
    r"\b([A-Za-z][A-Za-z0-9.\-]{1,40}(?:\s+[A-Za-z][A-Za-z0-9.\-]{1,40}){0,2})['’]s\s+"
    r"([A-Za-z][A-Za-z0-9 \-]{0,40}?)\s+(?:is|:)\s+"
    + _SENTENCE_VALUE,
    flags=re.IGNORECASE,
)
_ATTRIBUTE_OF_ENTITY = re.compile(
    r"\b(?:the\s+)?([A-Za-z][A-Za-z0-9 \-]{1,40}?)\s+(?:of|for)\s+"
    r"([A-Za-z][A-Za-z0-9.\-]{1,40}(?:\s+[A-Za-z][A-Za-z0-9.\-]{1,40}){0,2})\s+"
    r"(?:is|:)\s+"
    + _SENTENCE_VALUE,
    flags=re.IGNORECASE,
)
_MY_ATTRIBUTE = re.compile(
    r"\bmy\s+([A-Za-z][A-Za-z0-9 \-]{0,40}?)\s+(?:is|:)\s+" + _SENTENCE_VALUE,
    flags=re.IGNORECASE,
)
_ENTITY_IS_MY = re.compile(
    r"\b([A-Za-z][A-Za-z0-9.\-]{1,40}(?:\s+[A-Za-z][A-Za-z0-9.\-]{1,40}){0,2})\s+"
    r"is\s+my\s+([A-Za-z][A-Za-z0-9 \-]{1,40}?)"
    r"(?:[.!?](?:\s|$)|$)",
    flags=re.IGNORECASE,
)
_ACTION_PREFIX = re.compile(
    r"^\s*(?:please\s+)?(?:send|draft|create|schedule|search|find|look\s*up|"
    r"email|mail|text|message|call|remind)\b",
    flags=re.IGNORECASE,
)

_ENTITY_STOP = {
    "a", "an", "the", "my", "his", "her", "their", "our", "your", "me", "him", "them",
    "this", "that", "these", "those", "it", "please", "user", "remember", "forget",
    "i", "we", "you", "they", "who", "what", "when", "where", "why", "how",
    "there", "here", "someone", "anyone",
}
_ATTRIBUTE_STOP = {
    "reason", "purpose", "point", "thing", "way", "one", "idea", "issue", "problem",
    "question", "case", "kind", "sort", "type", "guess", "feeling", "thought",
    "impression", "take", "view", "fault", "bad", "good", "sense",
}
_VALUE_STOP = {
    "this", "that", "it", "them", "important", "true", "false", "ok", "okay", "fine",
    "ready", "done", "here", "there",
}


def _normalize_whitespace(value: str) -> str:
    return " ".join(str(value).split())


def _clean_extracted_fact(value: str) -> str:
    return _normalize_whitespace(value).strip(" .!?,;:")


def _title_entity(value: str) -> str:
    cleaned = _clean_extracted_fact(value)
    cleaned = re.sub(r"['’]s$", "", cleaned, flags=re.IGNORECASE)
    if not cleaned:
        return ""
    return " ".join(part.capitalize() for part in re.split(r"\s+", cleaned) if part)


def _valid_entity(value: str) -> bool:
    parts = [part.lower() for part in value.split() if part]
    if not parts:
        return False
    return not any(part in _ENTITY_STOP for part in parts)


def _valid_attribute(value: str) -> bool:
    cleaned = _clean_extracted_fact(value).lower()
    if not cleaned or len(cleaned.split()) > 4:
        return False
    return cleaned not in _ATTRIBUTE_STOP


def _valid_value(value: str) -> bool:
    cleaned = _clean_extracted_fact(value)
    if not cleaned or len(cleaned) < 2:
        return False
    lowered = cleaned.lower()
    if lowered in _VALUE_STOP:
        return False
    if "?" in lowered:
        return False
    return True


def _looks_like_action_request(text: str) -> bool:
    if not _ACTION_PREFIX.search(text):
        return False
    if _REMEMBER.search(text) or _DO_NOT_FORGET.search(text):
        return False
    if _POSSESSIVE_FACT.search(text) or _ATTRIBUTE_OF_ENTITY.search(text):
        return False
    if _MY_ATTRIBUTE.search(text) or _ENTITY_IS_MY.search(text):
        return False
    return True


def _append_fact(
    facts: List[SemanticFactWrite],
    seen: Set[tuple[str, str]],
    *,
    category: str,
    fact_text: str,
    confidence: float,
) -> None:
    key = (category, fact_text.lower())
    if key in seen:
        return
    seen.add(key)
    facts.append(
        SemanticFactWrite(
            category=category,
            fact_text=fact_text,
            source="deterministic_explicit_chat",
            confidence=confidence,
            explicit=True,
        )
    )


def extract_explicit_facts_from_user_text(user_text: str) -> List[SemanticFactWrite]:
    text = str(user_text or "")
    if not text.strip() or _looks_like_action_request(text):
        return []

    facts: List[SemanticFactWrite] = []
    seen: Set[tuple[str, str]] = set()

    for match in _REMEMBER.finditer(text):
        extracted = _clean_extracted_fact(match.group(1))
        if extracted:
            _append_fact(facts, seen, category="user_fact", fact_text=f"Remember that {extracted}", confidence=0.98)

    for match in _DO_NOT_FORGET.finditer(text):
        extracted = _clean_extracted_fact(match.group(1))
        if extracted:
            _append_fact(facts, seen, category="user_fact", fact_text=f"Do not forget that {extracted}", confidence=0.98)

    for match in _MY_ATTRIBUTE.finditer(text):
        attribute = _clean_extracted_fact(match.group(1))
        value = _clean_extracted_fact(match.group(2))
        if _valid_attribute(attribute) and _valid_value(value):
            _append_fact(
                facts,
                seen,
                category="user_profile",
                fact_text=f"User's {attribute.lower()} is {value}",
                confidence=0.99,
            )

    for match in _POSSESSIVE_FACT.finditer(text):
        entity = _title_entity(match.group(1))
        attribute = _clean_extracted_fact(match.group(2))
        value = _clean_extracted_fact(match.group(3))
        if _valid_entity(entity) and _valid_attribute(attribute) and _valid_value(value):
            _append_fact(
                facts,
                seen,
                category="user_fact",
                fact_text=f"{entity}'s {attribute.lower()} is {value}",
                confidence=0.97,
            )

    for match in _ATTRIBUTE_OF_ENTITY.finditer(text):
        attribute = _clean_extracted_fact(match.group(1))
        entity = _title_entity(match.group(2))
        value = _clean_extracted_fact(match.group(3))
        if _valid_entity(entity) and _valid_attribute(attribute) and _valid_value(value):
            _append_fact(
                facts,
                seen,
                category="user_fact",
                fact_text=f"{entity}'s {attribute.lower()} is {value}",
                confidence=0.96,
            )

    for match in _ENTITY_IS_MY.finditer(text):
        entity = _title_entity(match.group(1))
        role = _clean_extracted_fact(match.group(2))
        if _valid_entity(entity) and _valid_attribute(role):
            _append_fact(
                facts,
                seen,
                category="user_fact",
                fact_text=f"{entity} is the user's {role.lower()}",
                confidence=0.96,
            )

    return facts
