import re
from dataclasses import dataclass, field
from typing import Any, Literal, Optional, Sequence

from src.memory.episode_detector import EpisodeSourceWindow
from src.memory.episode_store import StructuredEpisodeRecord
from src.memory.summary_blocks import RawTurnRecord, SummaryBlockRecord


EpisodeContinuationAction = Literal["CREATE", "UPDATE", "MERGE", "SPLIT"]

STOPWORDS = {
    "about",
    "after",
    "again",
    "also",
    "and",
    "are",
    "because",
    "for",
    "from",
    "have",
    "into",
    "that",
    "the",
    "this",
    "new",
    "topic",
    "should",
    "split",
    "was",
    "were",
    "with",
    "you",
    "your",
}
SPLIT_MARKERS = (
    "separate topic",
    "new topic:",
    "actually split this",
    "this is unrelated to",
)


@dataclass(frozen=True)
class EpisodeContinuationConfig:
    update_threshold: float = 0.45
    merge_related_threshold: float = 0.35
    merge_combined_threshold: float = 0.55
    split_threshold: float = 0.40
    recent_episode_limit: int = 20


@dataclass(frozen=True)
class EpisodeContinuationDecision:
    action: EpisodeContinuationAction
    parent_episode_id: Optional[str]
    related_episode_ids: list[str] = field(default_factory=list)
    score: float = 0.0
    rationale_code: str = "no_related_episode"
    diagnostics: dict[str, Any] = field(default_factory=dict)


def tokenize_for_episode_similarity(text: str) -> set[str]:
    tokens = re.findall(r"[a-z0-9]+", str(text or "").casefold())
    return {token for token in tokens if len(token) >= 3 and token not in STOPWORDS}


def _tokens_from_turns(source_window: EpisodeSourceWindow, raw_turns: Sequence[RawTurnRecord]) -> set[str]:
    ids = set(source_window.turn_ids)
    text = "\n".join(turn.content for turn in raw_turns if turn.id in ids)
    return tokenize_for_episode_similarity(text)


def _tokens_from_summary_blocks(
    source_window: EpisodeSourceWindow,
    summary_blocks: Sequence[SummaryBlockRecord],
) -> set[str]:
    ids = set(source_window.summary_block_ids)
    text = "\n".join(block.summary for block in summary_blocks if block.id in ids)
    return tokenize_for_episode_similarity(text)


def _episode_tokens(episode: StructuredEpisodeRecord) -> dict[str, set[str]]:
    return {
        "title_summary": tokenize_for_episode_similarity(f"{episode.title} {episode.summary}"),
        "topics_artifacts": tokenize_for_episode_similarity(" ".join(episode.topics + episode.artifacts)),
        "goals_decisions": tokenize_for_episode_similarity(" ".join(episode.goals + episode.decisions)),
    }


def _weighted_score(candidate_tokens: set[str], episode: StructuredEpisodeRecord) -> float:
    if not candidate_tokens:
        return 0.0
    groups = _episode_tokens(episode)
    weighted_overlap = 0.0
    total_weight = 0.0
    weights = {
        "title_summary": 1.0,
        "topics_artifacts": 1.6,
        "goals_decisions": 1.3,
    }
    for name, tokens in groups.items():
        if not tokens:
            continue
        union_size = len(candidate_tokens.union(tokens))
        overlap = len(candidate_tokens.intersection(tokens)) / union_size if union_size else 0.0
        weighted_overlap += overlap * weights[name]
        total_weight += weights[name]
    return weighted_overlap / total_weight if total_weight else 0.0


def _has_split_marker(raw_turns: Sequence[RawTurnRecord], source_window: EpisodeSourceWindow) -> bool:
    ids = set(source_window.turn_ids)
    text = "\n".join(turn.content for turn in raw_turns if turn.id in ids).casefold()
    return any(marker in text for marker in SPLIT_MARKERS)


def decide_episode_continuation(
    *,
    source_window: EpisodeSourceWindow,
    raw_turns: Sequence[RawTurnRecord],
    existing_episodes: Sequence[StructuredEpisodeRecord],
    summary_blocks: Sequence[SummaryBlockRecord] = (),
    config: Optional[EpisodeContinuationConfig] = None,
) -> EpisodeContinuationDecision:
    cfg = config if config is not None else EpisodeContinuationConfig()
    recent = list(existing_episodes)[-cfg.recent_episode_limit :]
    candidate_tokens = _tokens_from_turns(source_window, raw_turns)
    candidate_tokens.update(_tokens_from_summary_blocks(source_window, summary_blocks))

    scored = [
        (episode, min(1.0, _weighted_score(candidate_tokens, episode) + (index / max(1, len(recent))) * 0.03))
        for index, episode in enumerate(recent)
    ]
    scored.sort(key=lambda item: (item[1], item[0].created_at, item[0].id), reverse=True)

    if not scored:
        return EpisodeContinuationDecision(
            action="CREATE",
            parent_episode_id=None,
            related_episode_ids=[],
            score=0.0,
            rationale_code="no_existing_episodes",
            diagnostics={"candidate_token_count": len(candidate_tokens), "scores": []},
        )

    best_episode, best_score = scored[0]
    related = [(episode, score) for episode, score in scored if score >= cfg.merge_related_threshold]
    split_marker = _has_split_marker(raw_turns, source_window)
    diagnostics = {
        "candidate_token_count": len(candidate_tokens),
        "split_marker": split_marker,
        "scores": [{"episode_id": episode.id, "score": score} for episode, score in scored],
    }

    if split_marker and best_score >= cfg.split_threshold:
        return EpisodeContinuationDecision(
            action="SPLIT",
            parent_episode_id=best_episode.id,
            related_episode_ids=[best_episode.id],
            score=best_score,
            rationale_code="explicit_split_marker",
            diagnostics=diagnostics,
        )

    combined_score = sum(score for _, score in related[:3])
    if len(related) >= 2 and combined_score >= cfg.merge_combined_threshold:
        return EpisodeContinuationDecision(
            action="MERGE",
            parent_episode_id=related[0][0].id,
            related_episode_ids=[episode.id for episode, _ in related[:3]],
            score=combined_score,
            rationale_code="multiple_related_episodes",
            diagnostics=diagnostics,
        )

    if best_score >= cfg.update_threshold:
        return EpisodeContinuationDecision(
            action="UPDATE",
            parent_episode_id=best_episode.id,
            related_episode_ids=[best_episode.id],
            score=best_score,
            rationale_code="single_related_episode",
            diagnostics=diagnostics,
        )

    return EpisodeContinuationDecision(
        action="CREATE",
        parent_episode_id=None,
        related_episode_ids=[],
        score=best_score,
        rationale_code="below_similarity_threshold",
        diagnostics=diagnostics,
    )





