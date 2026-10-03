import json
import logging
import time

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional, Protocol


ALL_MEMORY_JOB_TYPES = (
    "summary_generation",
    "cognee_ingest",
    "memory_session_write",
    "memory_session_merge",
)


@dataclass(frozen=True)
class JobHandlerResult:
    success: bool
    result: Dict[str, Any]
    retryable: bool = True


class MemoryJobHandler(Protocol):
    job_type: str

    def handle(self, job: Mapping[str, Any], payload: Mapping[str, Any]) -> JobHandlerResult:
        ...


@dataclass(frozen=True)
class NoOpMemoryJobHandler:
    job_type: str

    def handle(self, job: Mapping[str, Any], payload: Mapping[str, Any]) -> JobHandlerResult:
        if not isinstance(payload, Mapping):
            return JobHandlerResult(
                success=False,
                result={
                    "handler": "noop",
                    "job_type": self.job_type,
                    "processed": False,
                    "phase": "3B",
                    "message": "Payload must be a JSON object",
                },
            )
        if "schema_version" not in payload:
            return JobHandlerResult(
                success=False,
                result={
                    "handler": "noop",
                    "job_type": self.job_type,
                    "processed": False,
                    "phase": "3B",
                    "message": "Payload is missing schema_version",
                },
            )

        return JobHandlerResult(
            success=True,
            result={
                "handler": "noop",
                "job_type": self.job_type,
                "processed": False,
                "phase": "3B",
                "message": "Infrastructure-only handler; real behavior is implemented in later phases",
            },
        )



def _resolve_secondary_route(payload: Mapping[str, Any]):
    from src.harness.llm_router import resolve_secondary_from_job_payload

    return resolve_secondary_from_job_payload(payload)



@dataclass(frozen=True)
class SummaryGenerationJobHandler:
    job_type: str = "summary_generation"

    def handle(self, job: Mapping[str, Any], payload: Mapping[str, Any]) -> JobHandlerResult:
        if not isinstance(payload, Mapping):
            return JobHandlerResult(
                success=False,
                retryable=False,
                result={
                    "handler": "summary_generation",
                    "job_type": self.job_type,
                    "processed": False,
                    "phase": "5B",
                    "message": "Payload must be a JSON object",
                },
            )
        if "schema_version" not in payload:
            return JobHandlerResult(
                success=False,
                retryable=False,
                result={
                    "handler": "summary_generation",
                    "job_type": self.job_type,
                    "processed": False,
                    "phase": "5B",
                    "message": "Payload is missing schema_version",
                },
            )

        summary_payload = payload.get("summary_generation")
        if not isinstance(summary_payload, Mapping):
            return JobHandlerResult(
                success=False,
                retryable=False,
                result={
                    "handler": "summary_generation",
                    "job_type": self.job_type,
                    "processed": False,
                    "phase": "5B",
                    "message": "Payload is missing summary_generation object",
                },
            )

        selected_turn_ids = summary_payload.get("selected_turn_ids")
        if not isinstance(selected_turn_ids, list) or not selected_turn_ids:
            return JobHandlerResult(
                success=False,
                retryable=False,
                result={
                    "handler": "summary_generation",
                    "job_type": self.job_type,
                    "processed": False,
                    "phase": "5B",
                    "message": "summary_generation.selected_turn_ids must be a non-empty list",
                },
            )
        selected_turn_ids = [str(turn_id) for turn_id in selected_turn_ids]

        from src.memory.summary_blocks import SummaryBlockRepository

        repository = SummaryBlockRepository()
        existing = repository.get_by_source_job_id(str(job.get("id") or ""))
        if existing is not None:
            return JobHandlerResult(
                success=True,
                result={
                    "handler": "summary_generation",
                    "job_type": self.job_type,
                    "processed": False,
                    "phase": "5B",
                    "message": "Summary block already exists for job",
                    "summary_block_id": existing.id,
                    "covered_turn_count": len(existing.covered_message_ids),
                },
            )

        route = _resolve_secondary_route(payload)
        if not getattr(route, "available", False) or getattr(route, "llm", None) is None:
            return JobHandlerResult(
                success=False,
                retryable=True,
                result={
                    "handler": "summary_generation",
                    "job_type": self.job_type,
                    "processed": False,
                    "phase": "5B",
                    "message": "Secondary LLM unavailable",
                },
            )

        session_id = str(payload.get("session_id") or job.get("session_id") or "default_session")
        turns = repository.list_raw_turns_by_ids(session_id=session_id, turn_ids=selected_turn_ids)
        if [turn.id for turn in turns] != selected_turn_ids:
            return JobHandlerResult(
                success=False,
                retryable=False,
                result={
                    "handler": "summary_generation",
                    "job_type": self.job_type,
                    "processed": False,
                    "phase": "5B",
                    "message": "Selected raw turns were not found",
                },
            )

        turn_text = "\n".join(f"{turn.sender}: {turn.content}" for turn in turns)
        prompt = (
            "Summarize these conversation turns concisely. Preserve user preferences, "
            "decisions, open tasks, constraints, and important context. Return only the summary.\n\n"
            f"{turn_text}"
        )
        try:
            response = route.llm.invoke(prompt)
            summary_text = str(getattr(response, "content", response)).strip()
        except Exception as exc:
            return JobHandlerResult(
                success=False,
                retryable=True,
                result={
                    "handler": "summary_generation",
                    "job_type": self.job_type,
                    "processed": False,
                    "phase": "5B",
                    "message": "Summary LLM invocation failed",
                    "error_type": type(exc).__name__,
                },
            )

        if not summary_text:
            return JobHandlerResult(
                success=False,
                retryable=True,
                result={
                    "handler": "summary_generation",
                    "job_type": self.job_type,
                    "processed": False,
                    "phase": "5B",
                    "message": "Summary LLM returned empty output",
                },
            )

        from src.memory.token_budget import count_message_tokens
        from langchain_core.messages import AIMessage

        selector = route.selector
        summary_tokens = count_message_tokens(
            [AIMessage(content=summary_text)],
            provider=selector.provider,
            model_name=selector.model_name,
        )
        original_tokens = sum(int(turn.token_count or 0) for turn in turns)
        try:
            block = repository.append_summary_block(
                session_id=session_id,
                summary=summary_text,
                covered_message_ids=selected_turn_ids,
                start_message_id=summary_payload.get("start_message_id"),
                end_message_id=summary_payload.get("end_message_id"),
                source_job_id=str(job.get("id") or ""),
                token_count=summary_tokens,
                original_token_count=original_tokens,
                model_provider=selector.provider,
                model_name=selector.model_name,
            )
        except Exception as exc:
            return JobHandlerResult(
                success=False,
                retryable=True,
                result={
                    "handler": "summary_generation",
                    "job_type": self.job_type,
                    "processed": False,
                    "phase": "5B",
                    "message": "Failed to append summary block",
                    "error_type": type(exc).__name__,
                },
            )

        return JobHandlerResult(
            success=True,
            result={
                "handler": "summary_generation",
                "job_type": self.job_type,
                "processed": True,
                "phase": "5B",
                "message": "Summary block appended",
                "summary_block_id": block.id,
                "covered_turn_count": len(block.covered_message_ids),
                "summary_token_count": block.token_count,
                "original_token_count": block.original_token_count,
            },
        )


def _cognee_failure(job_type: str, message: str, *, retryable: bool) -> JobHandlerResult:
    return JobHandlerResult(
        success=False,
        retryable=retryable,
        result={"handler": job_type, "job_type": job_type, "processed": False, "message": message},
    )


def _utcnow() -> datetime:
    """Current UTC time (naive, matching SQLite timestamps). Patched in tests."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _parse_ts(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("T", " ").replace("Z", "").split(".")[0])
    except ValueError:
        return None


def _session_ids(payload: Mapping[str, Any]) -> Optional[tuple[str, str]]:
    from src.memory.config import load_memory_config

    session_id = str(payload.get("session_id") or "").strip()
    if not session_id:
        return None
    user_id = str(payload.get("user_id") or load_memory_config().cognee.user_id)
    return user_id, session_id


@dataclass(frozen=True)
class CogneeIngestJobHandler:
    """Writes explicit knowledge (API facts/procedures, legacy backfill) straight into the main graph."""

    job_type: str = "cognee_ingest"

    def handle(self, job: Mapping[str, Any], payload: Mapping[str, Any]) -> JobHandlerResult:
        from src.memory.cognee_memory import CogneeUnavailableError, get_cognee_memory

        documents = payload.get("documents")
        if not isinstance(documents, list) or not all(isinstance(item, str) for item in documents) or not documents:
            return _cognee_failure(self.job_type, "Payload must include a non-empty list of document strings", retryable=False)
        try:
            get_cognee_memory().remember_permanent(documents, user_id=payload.get("user_id"))
        except CogneeUnavailableError as exc:
            # Retrying cannot install or enable cognee; fail fast so the job is visible in dead letters.
            return _cognee_failure(self.job_type, str(exc), retryable=False)
        except Exception as exc:
            return _cognee_failure(self.job_type, f"cognee remember failed: {type(exc).__name__}", retryable=True)
        return JobHandlerResult(
            success=True,
            result={"handler": self.job_type, "job_type": self.job_type, "processed": True, "documents_added": len(documents)},
        )


@dataclass(frozen=True)
class MemorySessionWriteJobHandler:
    """Adds a worth-storing turn to the conversation's cognee session, then schedules the idle merge."""

    job_type: str = "memory_session_write"

    def handle(self, job: Mapping[str, Any], payload: Mapping[str, Any]) -> JobHandlerResult:
        from src.memory.cognee_memory import CogneeUnavailableError, get_cognee_memory
        from src.memory.events import log_memory_event
        from src.memory.jobs import SQLiteMemoryJobQueue, build_memory_session_merge_job_spec

        ids = _session_ids(payload)
        text = str(payload.get("text") or "").strip()
        if ids is None or not text:
            return _cognee_failure(self.job_type, "Payload must include session_id and text", retryable=False)
        user_id, session_id = ids
        memory = get_cognee_memory()
        started = time.monotonic()
        try:
            memory.remember_in_session(text, user_id=user_id, session_id=session_id)
        except CogneeUnavailableError as exc:
            log_memory_event("memory.session.write", user_id=user_id, session_id=session_id, success=False, error_category="CogneeUnavailableError")
            return _cognee_failure(self.job_type, str(exc), retryable=False)
        except Exception as exc:
            log_memory_event(
                "memory.session.write",
                level=logging.WARNING,
                user_id=user_id,
                session_id=session_id,
                success=False,
                error_category=type(exc).__name__,
                latency_ms=int((time.monotonic() - started) * 1000),
            )
            return _cognee_failure(self.job_type, f"cognee session write failed: {type(exc).__name__}", retryable=True)
        log_memory_event(
            "memory.session.write",
            user_id=user_id,
            session_id=session_id,
            success=True,
            latency_ms=int((time.monotonic() - started) * 1000),
        )

        due = _utcnow() + timedelta(minutes=memory.config.session_idle_timeout_minutes)
        merge = SQLiteMemoryJobQueue().enqueue_spec(
            build_memory_session_merge_job_spec(user_id=user_id, session_id=session_id, run_at=due)
        )
        return JobHandlerResult(
            success=True,
            result={
                "handler": self.job_type,
                "job_type": self.job_type,
                "processed": True,
                "merge_job_id": merge.job_id,
                "merge_due_at": due.strftime("%Y-%m-%d %H:%M:%S"),
            },
        )


def _session_activity(user_id: str, session_id: str) -> Dict[str, Any]:
    """Latest conversation activity, stored-write count, and how many writes were already merged."""
    from src.db import get_connection

    conn = get_connection()
    try:
        last_turn = conn.execute("SELECT MAX(created_at) FROM raw_turns WHERE session_id = ?", (session_id,)).fetchone()[0]
        write_count = conn.execute(
            """
            SELECT COUNT(*) FROM memory_jobs
            WHERE job_type = 'memory_session_write' AND status = 'SUCCEEDED'
              AND session_id = ? AND json_extract(payload_json, '$.user_id') = ?
            """,
            (session_id, user_id),
        ).fetchone()[0]
        merged_count = conn.execute(
            """
            SELECT MAX(json_extract(result_json, '$.merged_write_count')) FROM memory_jobs
            WHERE job_type = 'memory_session_merge' AND status = 'SUCCEEDED'
              AND session_id = ? AND json_extract(payload_json, '$.user_id') = ?
            """,
            (session_id, user_id),
        ).fetchone()[0]
    finally:
        conn.close()
    return {
        "last_turn": _parse_ts(last_turn),
        "write_count": int(write_count or 0),
        "merged_count": int(merged_count or 0),
    }


@dataclass(frozen=True)
class MemorySessionMergeJobHandler:
    """Merges an idle session's cognee cache into the main graph, at most once per batch of writes."""

    job_type: str = "memory_session_merge"

    def handle(self, job: Mapping[str, Any], payload: Mapping[str, Any]) -> JobHandlerResult:
        from src.memory.cognee_memory import CogneeMergeError, CogneeUnavailableError, get_cognee_memory
        from src.memory.events import log_memory_event
        from src.memory.jobs import SQLiteMemoryJobQueue, build_memory_session_merge_job_spec

        ids = _session_ids(payload)
        if ids is None:
            return _cognee_failure(self.job_type, "Payload must include session_id", retryable=False)
        user_id, session_id = ids
        memory = get_cognee_memory()
        timeout = timedelta(minutes=memory.config.session_idle_timeout_minutes)
        now = _utcnow()
        activity = _session_activity(user_id, session_id)

        base = {"handler": self.job_type, "job_type": self.job_type, "processed": True}
        last_turn = activity["last_turn"]
        if not payload.get("force") and last_turn is not None and now - last_turn < timeout:
            # The conversation resumed; push the merge to the end of the new quiet period.
            next_run = last_turn + timeout
            rescheduled = SQLiteMemoryJobQueue().enqueue_spec(
                build_memory_session_merge_job_spec(user_id=user_id, session_id=session_id, run_at=next_run)
            )
            return JobHandlerResult(success=True, result={**base, "deferred": True, "next_merge_job_id": rescheduled.job_id})

        # Successful write jobs only ever increase, so a count is a race-free high-water mark.
        write_count, merged_count = activity["write_count"], activity["merged_count"]
        if write_count <= merged_count:
            # Duplicate idle event, or nothing new was stored since the last merge.
            return JobHandlerResult(success=True, result={**base, "skipped": "nothing_to_merge"})

        started = time.monotonic()
        try:
            outcome = memory.merge_session(user_id=user_id, session_id=session_id)
        except CogneeUnavailableError as exc:
            log_memory_event("memory.session.merge", user_id=user_id, session_id=session_id, success=False, error_category="CogneeUnavailableError")
            return _cognee_failure(self.job_type, str(exc), retryable=False)
        except Exception as exc:
            log_memory_event(
                "memory.session.merge",
                level=logging.WARNING,
                user_id=user_id,
                session_id=session_id,
                success=False,
                error_category=type(exc).__name__,
                retryable=True,
                latency_ms=int((time.monotonic() - started) * 1000),
            )
            reason = "merge did not complete" if isinstance(exc, CogneeMergeError) else f"merge failed: {type(exc).__name__}"
            return _cognee_failure(self.job_type, reason, retryable=True)

        log_memory_event(
            "memory.session.merge",
            user_id=user_id,
            session_id=session_id,
            success=True,
            outcome=outcome.status,
            latency_ms=int((time.monotonic() - started) * 1000),
        )
        return JobHandlerResult(
            success=True,
            result={**base, "merged": True, "outcome": outcome.status, "merged_write_count": write_count},
        )


def build_default_handler_registry() -> Dict[str, MemoryJobHandler]:
    return {
        "summary_generation": SummaryGenerationJobHandler(),
        "cognee_ingest": CogneeIngestJobHandler(),
        "memory_session_write": MemorySessionWriteJobHandler(),
        "memory_session_merge": MemorySessionMergeJobHandler(),
    }
