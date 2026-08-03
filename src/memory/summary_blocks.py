import json
import math
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Optional, Sequence

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from src.db import get_connection
from src.memory.config import ShortTermMemoryConfig
from src.memory.token_budget import (
    ConversationTokenBudget,
    ProviderAwareTokenCounter,
    calculate_budget_for_primary_route,
    count_message_tokens,
)


SUMMARY_CONTEXT_PREFIX = "[Short-Term Summary Block"
SUMMARY_PENDING_NOTICE = (
    "[Short-Term Memory Notice]\n"
    "Earlier unsummarized turns are temporarily omitted while background summarization is pending."
)


@dataclass(frozen=True)
class RawTurnRecord:
    id: str
    session_id: str
    sender: str
    content: str
    token_count: int
    created_at: str


@dataclass(frozen=True)
class SummaryBlockRecord:
    id: str
    session_id: str
    sequence_number: int
    summary: str
    covered_message_ids: list[str]
    start_message_id: Optional[str]
    end_message_id: Optional[str]
    source_job_id: Optional[str]
    token_count: int
    original_token_count: Optional[int]
    model_provider: Optional[str]
    model_name: Optional[str]
    created_at: str


@dataclass(frozen=True)
class SummaryChunkSelection:
    session_id: str
    selected_turns: list[RawTurnRecord]
    selected_turn_ids: list[str]
    start_message_id: Optional[str]
    end_message_id: Optional[str]
    selected_token_count: int
    eligible_token_count: int
    chunk_ratio: float
    context_window: int


@dataclass(frozen=True)
class ReconstructedShortTermContext:
    messages: list[BaseMessage]
    summary_blocks: list[SummaryBlockRecord]
    recent_turns: list[RawTurnRecord]
    omitted_unsummarized_turn_ids: list[str]
    pending_summary_job_id: Optional[str]
    budget: ConversationTokenBudget
    status: Literal["WITHIN_BUDGET", "SUMMARY_PENDING", "SUMMARY_AVAILABLE", "ENQUEUE_FAILED"]


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _parse_json_list(value: Optional[str]) -> list[str]:
    if not value:
        return []
    try:
        decoded = json.loads(value)
    except Exception:
        return []
    if not isinstance(decoded, list):
        return []
    return [str(item) for item in decoded]


def _row_to_summary(row: Any) -> SummaryBlockRecord:
    return SummaryBlockRecord(
        id=str(row["id"]),
        session_id=str(row["session_id"]),
        sequence_number=int(row["sequence_number"]),
        summary=str(row["summary"]),
        covered_message_ids=_parse_json_list(row["covered_message_ids_json"]),
        start_message_id=row["start_message_id"],
        end_message_id=row["end_message_id"],
        source_job_id=row["source_job_id"],
        token_count=int(row["token_count"] or 0),
        original_token_count=(
            int(row["original_token_count"]) if row["original_token_count"] is not None else None
        ),
        model_provider=row["model_provider"],
        model_name=row["model_name"],
        created_at=str(row["created_at"]),
    )


def _row_to_raw_turn(row: Any) -> RawTurnRecord:
    return RawTurnRecord(
        id=str(row["id"]),
        session_id=str(row["session_id"]),
        sender=str(row["sender"]),
        content=str(row["content"]),
        token_count=int(row["tokens"] or 0),
        created_at=str(row["created_at"]),
    )


class SummaryBlockRepository:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path

    def append_summary_block(
        self,
        *,
        session_id: str,
        summary: str,
        covered_message_ids: Sequence[str],
        start_message_id: Optional[str],
        end_message_id: Optional[str],
        source_job_id: Optional[str],
        token_count: int,
        original_token_count: Optional[int],
        model_provider: Optional[str],
        model_name: Optional[str],
    ) -> SummaryBlockRecord:
        clean_summary = str(summary or "").strip()
        covered_ids = [str(turn_id) for turn_id in covered_message_ids if str(turn_id).strip()]
        if not clean_summary:
            raise ValueError("summary must not be empty")
        if not covered_ids:
            raise ValueError("covered_message_ids must not be empty")

        conn = get_connection(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT MAX(sequence_number) FROM summary_blocks WHERE session_id = ?",
                (session_id,),
            )
            next_sequence = int(cursor.fetchone()[0] or 0) + 1
            block_id = f"summary_{uuid.uuid4().hex[:16]}"
            cursor.execute(
                """
                INSERT INTO summary_blocks (
                    id,
                    session_id,
                    sequence_number,
                    summary,
                    covered_message_ids_json,
                    start_message_id,
                    end_message_id,
                    source_job_id,
                    token_count,
                    original_token_count,
                    model_provider,
                    model_name,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (
                    block_id,
                    session_id,
                    next_sequence,
                    clean_summary,
                    _canonical_json(covered_ids),
                    start_message_id,
                    end_message_id,
                    source_job_id,
                    max(0, int(token_count)),
                    max(0, int(original_token_count)) if original_token_count is not None else None,
                    model_provider,
                    model_name,
                ),
            )
            conn.commit()
            cursor.execute("SELECT * FROM summary_blocks WHERE id = ?", (block_id,))
            return _row_to_summary(cursor.fetchone())
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def list_summary_blocks(
        self,
        session_id: str,
        limit: Optional[int] = None,
        newest_first: bool = False,
    ) -> list[SummaryBlockRecord]:
        order = "DESC" if newest_first else "ASC"
        sql = f"""
            SELECT *
            FROM summary_blocks
            WHERE session_id = ?
            ORDER BY sequence_number {order}, created_at {order}, rowid {order}
        """
        params: list[Any] = [session_id]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(max(0, int(limit)))

        conn = get_connection(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(sql, tuple(params))
            return [_row_to_summary(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_by_source_job_id(self, source_job_id: str) -> Optional[SummaryBlockRecord]:
        conn = get_connection(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT *
                FROM summary_blocks
                WHERE source_job_id = ?
                ORDER BY sequence_number ASC
                LIMIT 1
                """,
                (source_job_id,),
            )
            row = cursor.fetchone()
            return _row_to_summary(row) if row else None
        finally:
            conn.close()

    def get_covered_message_ids(self, session_id: str) -> set[str]:
        covered: set[str] = set()
        for block in self.list_summary_blocks(session_id=session_id):
            covered.update(block.covered_message_ids)
        return covered

    def list_raw_turns(self, session_id: str) -> list[RawTurnRecord]:
        conn = get_connection(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, session_id, sender, content, tokens, created_at
                FROM raw_turns
                WHERE session_id = ?
                ORDER BY created_at ASC, rowid ASC
                """,
                (session_id,),
            )
            return [_row_to_raw_turn(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def list_raw_turns_by_ids(self, session_id: str, turn_ids: Sequence[str]) -> list[RawTurnRecord]:
        ordered_ids = [str(turn_id) for turn_id in turn_ids if str(turn_id).strip()]
        if not ordered_ids:
            return []

        placeholders = ",".join("?" for _ in ordered_ids)
        conn = get_connection(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                f"""
                SELECT id, session_id, sender, content, tokens, created_at
                FROM raw_turns
                WHERE session_id = ?
                  AND id IN ({placeholders})
                """,
                (session_id, *ordered_ids),
            )
            rows_by_id = {str(row["id"]): _row_to_raw_turn(row) for row in cursor.fetchall()}
            return [rows_by_id[turn_id] for turn_id in ordered_ids if turn_id in rows_by_id]
        finally:
            conn.close()


def get_adaptive_summary_chunk_ratio(context_window: int) -> float:
    if context_window <= 200000:
        return 0.30
    if context_window <= 500000:
        return 0.25
    return 0.20


def _turn_token_count(
    turn: RawTurnRecord,
    provider: str,
    model_name: str,
    counter: Optional[ProviderAwareTokenCounter],
) -> int:
    if turn.token_count > 0:
        return turn.token_count
    return count_message_tokens(
        [_raw_turn_to_message(turn)],
        provider=provider,
        model_name=model_name,
        counter=counter,
    )


def _latest_current_user_turn_id(raw_turns: Sequence[RawTurnRecord]) -> Optional[str]:
    for turn in reversed(raw_turns):
        if turn.sender == "user":
            return turn.id
    return None


def select_oldest_summary_chunk(
    *,
    session_id: str,
    context_window: int,
    repository: SummaryBlockRepository,
    provider: str = "openai",
    model_name: str = "gpt-4o-mini",
    current_user_turn_id: Optional[str] = None,
    counter: Optional[ProviderAwareTokenCounter] = None,
) -> Optional[SummaryChunkSelection]:
    raw_turns = repository.list_raw_turns(session_id=session_id)
    covered_ids = repository.get_covered_message_ids(session_id)
    latest_user_id = current_user_turn_id or _latest_current_user_turn_id(raw_turns)
    eligible_turns = [
        turn
        for turn in raw_turns
        if turn.id not in covered_ids
        and turn.id != latest_user_id
        and turn.content.strip()
    ]
    if not eligible_turns:
        return None

    token_pairs = [
        (turn, _turn_token_count(turn, provider=provider, model_name=model_name, counter=counter))
        for turn in eligible_turns
    ]
    eligible_token_count = sum(tokens for _, tokens in token_pairs)
    if eligible_token_count <= 0:
        return None

    ratio = get_adaptive_summary_chunk_ratio(context_window)
    target_tokens = max(1, math.ceil(eligible_token_count * ratio))
    selected: list[RawTurnRecord] = []
    selected_token_count = 0
    for turn, tokens in token_pairs:
        selected.append(turn)
        selected_token_count += tokens
        if selected_token_count >= target_tokens:
            break

    if selected_token_count <= 0:
        return None

    return SummaryChunkSelection(
        session_id=session_id,
        selected_turns=selected,
        selected_turn_ids=[turn.id for turn in selected],
        start_message_id=selected[0].id,
        end_message_id=selected[-1].id,
        selected_token_count=selected_token_count,
        eligible_token_count=eligible_token_count,
        chunk_ratio=ratio,
        context_window=context_window,
    )


def _summary_block_to_message(block: SummaryBlockRecord) -> SystemMessage:
    return SystemMessage(content=f"{SUMMARY_CONTEXT_PREFIX} #{block.sequence_number}]\n{block.summary}")


def _raw_turn_to_message(turn: RawTurnRecord) -> BaseMessage:
    if turn.sender == "assistant":
        return AIMessage(content=turn.content)
    return HumanMessage(content=turn.content)


def _select_recent_turns_that_fit(
    turns: Sequence[RawTurnRecord],
    token_budget: int,
    provider: str,
    model_name: str,
    counter: Optional[ProviderAwareTokenCounter],
) -> tuple[list[RawTurnRecord], list[str]]:
    selected_reversed: list[RawTurnRecord] = []
    selected_tokens = 0
    omitted_ids: list[str] = []

    for turn in reversed(list(turns)):
        turn_tokens = _turn_token_count(turn, provider=provider, model_name=model_name, counter=counter)
        if selected_tokens + turn_tokens <= token_budget:
            selected_reversed.append(turn)
            selected_tokens += turn_tokens
        else:
            omitted_ids.append(turn.id)

    return list(reversed(selected_reversed)), list(reversed(omitted_ids))


def prepare_short_term_context_for_chat(
    *,
    session_id: str,
    current_messages: Sequence[BaseMessage],
    provider: Optional[str],
    model_name: Optional[str],
    secondary_provider: Optional[str] = None,
    secondary_model_name: Optional[str] = None,
    repository: Optional[SummaryBlockRepository] = None,
    queue: Any = None,
    config: Optional[ShortTermMemoryConfig] = None,
    counter: Optional[ProviderAwareTokenCounter] = None,
) -> ReconstructedShortTermContext:
    repo = repository if repository is not None else SummaryBlockRepository()
    current_message_list = list(current_messages or [])
    system_messages = [message for message in current_message_list if isinstance(message, SystemMessage)]
    current_user_message = next(
        (message for message in reversed(current_message_list) if isinstance(message, HumanMessage)),
        None,
    )

    try:
        summary_blocks = repo.list_summary_blocks(session_id=session_id)
        raw_turns = repo.list_raw_turns(session_id=session_id)
    except Exception:
        fallback_budget = calculate_budget_for_primary_route(
            provider=provider,
            model_name=model_name,
            messages=current_message_list,
            config=config,
            counter=counter,
        )
        return ReconstructedShortTermContext(
            messages=current_message_list,
            summary_blocks=[],
            recent_turns=[],
            omitted_unsummarized_turn_ids=[],
            pending_summary_job_id=None,
            budget=fallback_budget,
            status="ENQUEUE_FAILED",
        )

    covered_ids = repo.get_covered_message_ids(session_id)
    current_user_turn_id = _latest_current_user_turn_id(raw_turns)
    uncovered_historical_turns = [
        turn
        for turn in raw_turns
        if turn.id not in covered_ids and turn.id != current_user_turn_id
    ]
    summary_messages = [_summary_block_to_message(block) for block in summary_blocks]
    historical_messages = [_raw_turn_to_message(turn) for turn in uncovered_historical_turns]
    budget_messages = system_messages + summary_messages + historical_messages
    if current_user_message is not None:
        budget_messages.append(current_user_message)

    budget = calculate_budget_for_primary_route(
        provider=provider,
        model_name=model_name,
        messages=budget_messages,
        config=config,
        counter=counter,
    )

    pending_summary_job_id: Optional[str] = None
    status: Literal["WITHIN_BUDGET", "SUMMARY_PENDING", "SUMMARY_AVAILABLE", "ENQUEUE_FAILED"]
    status = "SUMMARY_AVAILABLE" if summary_blocks else "WITHIN_BUDGET"

    if budget.should_trigger_summarization:
        selection = select_oldest_summary_chunk(
            session_id=session_id,
            context_window=budget.context_window,
            repository=repo,
            provider=budget.provider,
            model_name=budget.model_name,
            current_user_turn_id=current_user_turn_id,
            counter=counter,
        )
        if selection is not None:
            try:
                from src.memory.jobs import enqueue_summary_generation_job

                result = enqueue_summary_generation_job(
                    selection=selection,
                    budget=budget,
                    primary_provider=budget.provider,
                    primary_model_name=budget.model_name,
                    secondary_provider=secondary_provider or budget.provider,
                    secondary_model_name=secondary_model_name or "gpt-4o-mini",
                    queue=queue,
                )
                pending_summary_job_id = result.job_id
                status = "SUMMARY_PENDING"
            except Exception:
                status = "ENQUEUE_FAILED"

    recent_turns, omitted_ids = _select_recent_turns_that_fit(
        uncovered_historical_turns,
        token_budget=budget.conversation_budget_tokens,
        provider=budget.provider,
        model_name=budget.model_name,
        counter=counter,
    )
    reconstructed = list(system_messages)
    reconstructed.extend(summary_messages)
    if omitted_ids:
        reconstructed.append(SystemMessage(content=SUMMARY_PENDING_NOTICE))
    reconstructed.extend(_raw_turn_to_message(turn) for turn in recent_turns)
    if current_user_message is not None:
        reconstructed.append(current_user_message)

    return ReconstructedShortTermContext(
        messages=reconstructed,
        summary_blocks=summary_blocks,
        recent_turns=recent_turns,
        omitted_unsummarized_turn_ids=omitted_ids,
        pending_summary_job_id=pending_summary_job_id,
        budget=budget,
        status=status,
    )

