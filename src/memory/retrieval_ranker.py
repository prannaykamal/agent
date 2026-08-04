import math
import re
from dataclasses import replace
from datetime import datetime, timezone
from typing import Mapping, Optional, Sequence, Tuple

from src.memory.retrieval_types import RetrievedMemoryCandidate, RetrievalScore


MEMORY_KIND_SORT_ORDER = {
    "semantic": 0,
    "episodic": 1,
    "procedural": 2,
    "summary": 3,
}

STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "i",
    "in",
    "is",
    "it",
    "my",
    "of",
    "on",
    "or",
    "our",
    "the",
    "to",
    "with",
    "you",
    "your",
}


def clamp_score(value: object) -> float:
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(parsed) or math.isinf(parsed):
        return 0.0
    return max(0.0, min(1.0, parsed))


def normalize_retrieval_text(text: object) -> str:
    return " ".join(str(text or "").lower().split())


def tokenize_retrieval_text(text: object) -> Tuple[str, ...]:
    normalized = normalize_retrieval_text(text)
    tokens = []
    seen = set()
    for token in re.findall(r"[a-z0-9]+", normalized):
        if token in STOP_WORDS:
            continue
        if len(token) <= 1 and not token.isdigit():
            continue
        if len(token) > 4 and token.endswith("s"):
            token = token[:-1]
        if token and token not in seen:
            seen.add(token)
            tokens.append(token)
    return tuple(tokens)


def lexical_similarity(left: object, right: object) -> float:
    left_normalized = normalize_retrieval_text(left)
    right_normalized = normalize_retrieval_text(right)
    if not left_normalized or not right_normalized:
        return 0.0
    left_tokens = set(tokenize_retrieval_text(left_normalized))
    right_tokens = set(tokenize_retrieval_text(right_normalized))
    if not left_tokens or not right_tokens:
        return 0.0
    intersection = len(left_tokens & right_tokens)
    union = len(left_tokens | right_tokens)
    containment = intersection / max(1, min(len(left_tokens), len(right_tokens)))
    jaccard = intersection / max(1, union)
    score = (0.75 * containment) + (0.25 * jaccard)
    if left_normalized in right_normalized or right_normalized in left_normalized:
        score = max(score, 0.95)
    return clamp_score(score)


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def recency_score(created_at: Optional[str], *, newest_at: Optional[str] = None) -> float:
    created = _parse_datetime(created_at)
    if created is None:
        return 0.0
    newest = _parse_datetime(newest_at) if newest_at is not None else datetime.now(timezone.utc)
    if newest is None:
        newest = datetime.now(timezone.utc)
    age_seconds = max(0.0, (newest - created).total_seconds())
    age_days = age_seconds / 86400.0
    return clamp_score(1.0 / (1.0 + age_days))


def weighted_score(components: Mapping[str, float], weights: Optional[Mapping[str, float]] = None) -> float:
    parsed_components = {str(key): clamp_score(value) for key, value in dict(components).items()}
    if not parsed_components:
        return 0.0
    if not weights:
        return clamp_score(sum(parsed_components.values()) / len(parsed_components))
    total_weight = 0.0
    weighted_total = 0.0
    for key, value in parsed_components.items():
        weight = max(0.0, float(weights.get(key, 0.0)))
        if weight <= 0:
            continue
        total_weight += weight
        weighted_total += value * weight
    if total_weight <= 0:
        return 0.0
    return clamp_score(weighted_total / total_weight)


def normalize_candidates(candidates: Sequence[RetrievedMemoryCandidate]) -> Tuple[RetrievedMemoryCandidate, ...]:
    items = tuple(candidates)
    if not items:
        return tuple()
    raw_scores = [candidate.score.raw_score for candidate in items]
    min_score = min(raw_scores)
    max_score = max(raw_scores)
    normalized = []
    for candidate in items:
        if max_score == min_score:
            normalized_score = 1.0 if candidate.score.raw_score > 0 else 0.0
        else:
            normalized_score = (candidate.score.raw_score - min_score) / (max_score - min_score)
        new_score = RetrievalScore(
            raw_score=candidate.score.raw_score,
            normalized_score=normalized_score,
            rank_score=normalized_score,
            components=dict(candidate.score.components),
            strategy=candidate.score.strategy,
        )
        normalized.append(replace(candidate, score=new_score))
    return tuple(normalized)


def _created_sort_value(candidate: RetrievedMemoryCandidate) -> float:
    parsed = _parse_datetime(candidate.provenance.created_at)
    return parsed.timestamp() if parsed is not None else 0.0


def rank_candidates(candidates: Sequence[RetrievedMemoryCandidate]) -> Tuple[RetrievedMemoryCandidate, ...]:
    return tuple(
        sorted(
            tuple(candidates),
            key=lambda candidate: (
                -candidate.score.rank_score,
                -candidate.score.normalized_score,
                -candidate.score.raw_score,
                MEMORY_KIND_SORT_ORDER.get(str(candidate.memory_kind), 99),
                -_created_sort_value(candidate),
                str(candidate.id),
            ),
        )
    )


def estimate_retrieval_candidate_tokens(
    candidate: RetrievedMemoryCandidate,
    *,
    provider: str = "openai",
    model_name: str = "gpt-4o-mini",
) -> int:
    del provider, model_name
    content = str(candidate.content or "")
    if not content:
        return 0
    return max(1, len(content) // 4)


def trim_retrieval_candidates_to_budget(
    candidates: Sequence[RetrievedMemoryCandidate],
    token_budget: Optional[int],
    *,
    provider: str = "openai",
    model_name: str = "gpt-4o-mini",
    allow_truncation: bool = False,
) -> tuple[Tuple[RetrievedMemoryCandidate, ...], Tuple[str, ...], int]:
    if token_budget is None:
        total = sum(
            candidate.token_count
            or estimate_retrieval_candidate_tokens(candidate, provider=provider, model_name=model_name)
            for candidate in candidates
        )
        return tuple(candidates), tuple(), max(0, int(total))

    budget = max(0, int(token_budget))
    kept = []
    omitted = []
    total = 0
    truncated = False
    for candidate in candidates:
        tokens = candidate.token_count or estimate_retrieval_candidate_tokens(
            candidate,
            provider=provider,
            model_name=model_name,
        )
        tokens = max(0, int(tokens))
        remaining = budget - total
        if tokens <= remaining:
            kept.append(replace(candidate, token_count=tokens))
            total += tokens
            continue
        if allow_truncation and remaining > 0 and not truncated:
            max_chars = max(0, remaining * 4)
            truncated_content = candidate.content[:max_chars].rstrip()
            debug = dict(candidate.debug)
            debug.update(
                {
                    "content_truncated": True,
                    "original_token_count": tokens,
                    "truncated_token_count": remaining,
                }
            )
            kept.append(
                replace(
                    candidate,
                    content=truncated_content,
                    token_count=remaining,
                    debug=debug,
                )
            )
            total += remaining
            truncated = True
        else:
            omitted.append(candidate.id)
    return tuple(kept), tuple(omitted), total
