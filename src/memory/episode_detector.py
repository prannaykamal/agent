import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Mapping, Optional, Sequence

from langchain_core.messages import AIMessage, HumanMessage

from src.memory.episode_store import StructuredEpisodeRecord
from src.memory.summary_blocks import RawTurnRecord, SummaryBlockRecord
from src.memory.token_budget import count_message_tokens


EpisodeTriggerReason = Literal[
    "explicit_memory_request",
    "trimming_occurred",
    "idle_timeout",
    "long_conversation",
    "task_completed",
    "workflow_finished",
]

_REASON_PRIORITY: tuple[EpisodeTriggerReason, ...] = (
    "explicit_memory_request",
    "trimming_occurred",
    "task_completed",
    "workflow_finished",
    "idle_timeout",
    "long_conversation",
)


@dataclass(frozen=True)
class EpisodeDetectorConfig:
    idle_timeout_seconds: int = 2700
    long_conversation_tokens: int = 50000
    max_source_turns: int = 40
    explicit_remember_patterns: tuple[str, ...] = (
        "remember this",
        "remember that",
        "please remember",
        "don't forget",
        "do not forget",
    )


@dataclass(frozen=True)
class EpisodeSourceWindow:
    session_id: str
    turn_ids: list[str]
    start_message_id: str
    end_message_id: str
    token_count: int
    user_text_hash: Optional[str]
    assistant_text_hash: Optional[str]
    summary_block_ids: list[str]
    source_text_mode: Literal["raw_turns", "summary_blocks", "mixed"]


@dataclass(frozen=True)
class EpisodeDetectionResult:
    should_enqueue: bool
    primary_reason: Optional[EpisodeTriggerReason]
    reasons: list[EpisodeTriggerReason] = field(default_factory=list)
    source_window: Optional[EpisodeSourceWindow] = None
    diagnostics: dict[str, Any] = field(default_factory=dict)


def _sha256_or_none(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _message_text(message: Any) -> str:
    content = getattr(message, "content", "")
    return str(content or "")


def _latest_user_text_from_state(state: Mapping[str, Any]) -> str:
    messages = list(state.get("messages") or [])
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return _message_text(message)
    return ""


def _latest_assistant_text_from_state(state: Mapping[str, Any]) -> str:
    messages = list(state.get("messages") or [])
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            return _message_text(message)
    return ""


def _latest_text_from_turns(raw_turns: Sequence[RawTurnRecord], sender: str) -> str:
    for turn in reversed(raw_turns):
        if turn.sender == sender and turn.content.strip():
            return turn.content
    return ""


def _explicit_memory_request(text: str, config: EpisodeDetectorConfig) -> bool:
    lowered = text.casefold()
    return any(pattern in lowered for pattern in config.explicit_remember_patterns)


def _parse_created_at(value: str) -> Optional[datetime]:
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _turn_tokens(turn: RawTurnRecord) -> int:
    if turn.token_count > 0:
        return int(turn.token_count)
    if not turn.content.strip():
        return 0
    message = AIMessage(content=turn.content) if turn.sender == "assistant" else HumanMessage(content=turn.content)
    return count_message_tokens([message])


def _covered_turn_ids(
    raw_turns: Sequence[RawTurnRecord],
    existing_episodes: Sequence[StructuredEpisodeRecord],
) -> set[str]:
    index_by_id = {turn.id: index for index, turn in enumerate(raw_turns)}
    covered: set[str] = set()
    for episode in existing_episodes:
        start_index = index_by_id.get(episode.start_message_id)
        end_index = index_by_id.get(episode.end_message_id)
        if start_index is None or end_index is None:
            continue
        if end_index < start_index:
            start_index, end_index = end_index, start_index
        covered.update(turn.id for turn in raw_turns[start_index : end_index + 1])
    return covered


def _select_explicit_window(turns: Sequence[RawTurnRecord], max_source_turns: int) -> list[RawTurnRecord]:
    if not turns:
        return []
    latest_user_index = next(
        (index for index in range(len(turns) - 1, -1, -1) if turns[index].sender == "user"),
        len(turns) - 1,
    )
    start = max(0, latest_user_index - 1)
    end = min(len(turns), latest_user_index + 2)
    window = list(turns[start:end])
    return window[-max_source_turns:]


def _select_source_turns(
    reason: EpisodeTriggerReason,
    turns: Sequence[RawTurnRecord],
    state: Mapping[str, Any],
    max_source_turns: int,
) -> list[RawTurnRecord]:
    if not turns:
        return []
    if reason == "explicit_memory_request":
        return _select_explicit_window(turns, max_source_turns)
    if reason == "long_conversation":
        return list(turns[:max_source_turns])
    if reason == "trimming_occurred":
        omitted_ids = [str(turn_id) for turn_id in (state.get("summary_omitted_turn_ids") or [])]
        if omitted_ids:
            by_id = {turn.id: turn for turn in turns}
            selected = [by_id[turn_id] for turn_id in omitted_ids if turn_id in by_id]
            if selected:
                return selected[:max_source_turns]
    return list(turns[-max_source_turns:])


def _summary_blocks_for_turns(
    selected_turn_ids: Sequence[str],
    summary_blocks: Sequence[SummaryBlockRecord],
) -> list[str]:
    selected = set(selected_turn_ids)
    block_ids: list[str] = []
    for block in summary_blocks:
        if selected.intersection(block.covered_message_ids):
            block_ids.append(block.id)
    return block_ids


def _build_source_window(
    *,
    session_id: str,
    reason: EpisodeTriggerReason,
    turns: Sequence[RawTurnRecord],
    state: Mapping[str, Any],
    summary_blocks: Sequence[SummaryBlockRecord],
    config: EpisodeDetectorConfig,
) -> Optional[EpisodeSourceWindow]:
    selected = _select_source_turns(reason, turns, state, config.max_source_turns)
    selected = [turn for turn in selected if turn.content.strip()]
    if not selected:
        return None

    turn_ids = [turn.id for turn in selected]
    latest_user = next((turn.content for turn in reversed(selected) if turn.sender == "user"), None)
    latest_assistant = next((turn.content for turn in reversed(selected) if turn.sender == "assistant"), None)
    block_ids = _summary_blocks_for_turns(turn_ids, summary_blocks)
    mode: Literal["raw_turns", "summary_blocks", "mixed"] = "raw_turns"
    if block_ids and len(block_ids) == len(turn_ids):
        mode = "summary_blocks"
    elif block_ids:
        mode = "mixed"

    return EpisodeSourceWindow(
        session_id=session_id,
        turn_ids=turn_ids,
        start_message_id=selected[0].id,
        end_message_id=selected[-1].id,
        token_count=sum(_turn_tokens(turn) for turn in selected),
        user_text_hash=_sha256_or_none(latest_user),
        assistant_text_hash=_sha256_or_none(latest_assistant),
        summary_block_ids=block_ids,
        source_text_mode=mode,
    )


def _idle_timeout_triggered(raw_turns: Sequence[RawTurnRecord], config: EpisodeDetectorConfig) -> tuple[bool, Optional[float]]:
    if len(raw_turns) < 2:
        return False, None
    latest_user_index = next(
        (index for index in range(len(raw_turns) - 1, -1, -1) if raw_turns[index].sender == "user"),
        None,
    )
    if latest_user_index is None or latest_user_index == 0:
        return False, None
    latest_ts = _parse_created_at(raw_turns[latest_user_index].created_at)
    previous_ts = _parse_created_at(raw_turns[latest_user_index - 1].created_at)
    if latest_ts is None or previous_ts is None:
        return False, None
    elapsed = (latest_ts - previous_ts).total_seconds()
    return elapsed >= config.idle_timeout_seconds, elapsed


def detect_episode_trigger(
    *,
    state: Mapping[str, Any],
    raw_turns: Sequence[RawTurnRecord],
    existing_episodes: Sequence[StructuredEpisodeRecord],
    summary_blocks: Sequence[SummaryBlockRecord] = (),
    now: Optional[datetime] = None,
    config: Optional[EpisodeDetectorConfig] = None,
) -> EpisodeDetectionResult:
    del now
    cfg = config if config is not None else EpisodeDetectorConfig()
    session_id = str(state.get("session_id") or (raw_turns[-1].session_id if raw_turns else "default_session"))
    covered_ids = _covered_turn_ids(raw_turns, existing_episodes)
    uncovered_turns = [turn for turn in raw_turns if turn.id not in covered_ids and turn.content.strip()]
    latest_user_text = _latest_user_text_from_state(state) or _latest_text_from_turns(raw_turns, "user")
    latest_assistant_text = _latest_assistant_text_from_state(state) or _latest_text_from_turns(raw_turns, "assistant")
    uncovered_tokens = sum(_turn_tokens(turn) for turn in uncovered_turns)
    idle_triggered, idle_seconds = _idle_timeout_triggered(raw_turns, cfg)

    metadata = state.get("trigger_metadata") if isinstance(state.get("trigger_metadata"), Mapping) else {}
    truth_by_reason: dict[EpisodeTriggerReason, bool] = {
        "explicit_memory_request": bool(metadata.get("explicit_memory_request")) or _explicit_memory_request(latest_user_text, cfg),
        "trimming_occurred": bool(state.get("trimming_occurred", False)) or bool(metadata.get("trimming_occurred")),
        "task_completed": bool(state.get("task_completed", False)) or bool(metadata.get("task_completed")),
        "workflow_finished": bool(state.get("workflow_finished", False)) or bool(metadata.get("workflow_finished")),
        "idle_timeout": idle_triggered,
        "long_conversation": uncovered_tokens >= cfg.long_conversation_tokens,
    }
    reasons = [reason for reason in _REASON_PRIORITY if truth_by_reason[reason]]
    primary_reason = reasons[0] if reasons else None

    source_window = (
        _build_source_window(
            session_id=session_id,
            reason=primary_reason,
            turns=uncovered_turns,
            state=state,
            summary_blocks=summary_blocks,
            config=cfg,
        )
        if primary_reason is not None
        else None
    )

    return EpisodeDetectionResult(
        should_enqueue=bool(primary_reason and source_window),
        primary_reason=primary_reason if source_window else None,
        reasons=reasons if source_window else [],
        source_window=source_window,
        diagnostics={
            "covered_turn_count": len(covered_ids),
            "uncovered_turn_count": len(uncovered_turns),
            "uncovered_token_count": uncovered_tokens,
            "idle_elapsed_seconds": idle_seconds,
            "latest_user_text_hash": _sha256_or_none(latest_user_text or None),
            "latest_assistant_text_hash": _sha256_or_none(latest_assistant_text or None),
        },
    )



