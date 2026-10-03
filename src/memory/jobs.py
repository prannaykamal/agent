import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from langchain_core.messages import AIMessage, HumanMessage

from src.harness.state import AgentState
from src.memory.config import QueueConfig, load_memory_config
from src.memory.types import MemoryJobType


PHASE_3A_PAYLOAD_SCHEMA_VERSION = 1
PHASE_5B_SUMMARY_PAYLOAD_SCHEMA_VERSION = 1
COGNEE_PAYLOAD_SCHEMA_VERSION = 1
MEMORY_JOB_STATUS_QUEUED = "QUEUED"
MEMORY_JOB_STATUS_RUNNING = "RUNNING"
MEMORY_JOB_STATUS_RETRYING = "RETRYING"
MEMORY_JOB_STATUS_SUCCEEDED = "SUCCEEDED"
MEMORY_JOB_STATUS_FAILED = "FAILED"
MEMORY_JOB_STATUS_DEAD_LETTERED = "DEAD_LETTERED"
MEMORY_JOB_STATUS_CANCELLED = "CANCELLED"
POST_TURN_SOURCE = "graph.post_turn"
SUMMARY_GENERATION_SOURCE = "graph.short_term_budget"
SESSION_MERGE_SOURCE = "memory.session_idle"
PHASE_3A_CREATED_BY = "phase_3a_enqueue"
PHASE_5B_CREATED_BY = "phase_5b_summary_enqueue"
COGNEE_CREATED_BY = "cognee_memory_enqueue"

_HITL_PAUSE_PREFIX = "[HUMAN APPROVAL REQUIRED"
_SUMMARY_JOB_TYPE: MemoryJobType = "summary_generation"
_COGNEE_INGEST_JOB_TYPE: MemoryJobType = "cognee_ingest"
_SESSION_WRITE_JOB_TYPE: MemoryJobType = "memory_session_write"
_SESSION_MERGE_JOB_TYPE: MemoryJobType = "memory_session_merge"


@dataclass(frozen=True)
class MemoryJobSpec:
    job_type: MemoryJobType
    payload: Dict[str, Any]
    idempotency_key: str
    job_id: str
    session_id: Optional[str] = None
    priority: int = 100
    available_at: Optional[str] = None


@dataclass(frozen=True)
class EnqueueResult:
    job_id: str
    idempotency_key: str
    inserted: bool
    status: str


def canonical_json(value: Mapping[str, Any]) -> str:
    """Return deterministic compact JSON for hashing and persistence."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _short_hash(value: str, length: int = 16) -> str:
    return sha256_hex(value)[:length]


def make_memory_job_id(job_type: str, idempotency_key: str) -> str:
    return f"memjob_{job_type}_{_short_hash(idempotency_key, 16)}"


def make_summary_generation_idempotency_key(
    session_id: str,
    selected_turn_ids: Sequence[str],
    secondary_provider: str,
    secondary_model_name: str,
    payload_schema_version: int = PHASE_5B_SUMMARY_PAYLOAD_SCHEMA_VERSION,
) -> str:
    canonical_input = {
        "schema_version": payload_schema_version,
        "job_type": _SUMMARY_JOB_TYPE,
        "session_id": session_id,
        "selected_turn_ids": [str(turn_id) for turn_id in selected_turn_ids],
        "secondary_provider": str(secondary_provider or "openai"),
        "secondary_model_name": str(secondary_model_name or "gpt-4o-mini"),
    }
    coverage_hash = _short_hash(canonical_json(canonical_input), 16)
    session_hash = _short_hash(session_id, 12)
    return f"memq:v1:{_SUMMARY_JOB_TYPE}:{session_hash}:{coverage_hash}"

def build_summary_generation_payload(
    *,
    session_id: str,
    selected_turn_ids: Sequence[str],
    start_message_id: Optional[str],
    end_message_id: Optional[str],
    selected_token_count: int,
    eligible_token_count: int,
    chunk_ratio: float,
    context_window: int,
    conversation_budget_tokens: int,
    summarization_trigger_tokens: int,
    historical_conversation_tokens: int,
    primary_provider: str,
    primary_model_name: str,
    secondary_provider: str,
    secondary_model_name: str,
) -> Dict[str, Any]:
    from src.harness.llm_router import normalize_provider

    selected_ids = [str(turn_id) for turn_id in selected_turn_ids]
    provider = normalize_provider(primary_provider)
    sec_provider = normalize_provider(secondary_provider)
    return {
        "schema_version": PHASE_5B_SUMMARY_PAYLOAD_SCHEMA_VERSION,
        "source": SUMMARY_GENERATION_SOURCE,
        "session_id": session_id,
        "models": {
            "primary_provider": provider,
            "primary_model_name": primary_model_name or "gpt-4o-mini",
            "secondary_provider": sec_provider,
            "secondary_model_name": secondary_model_name or "gpt-4o-mini",
        },
        "summary_generation": {
            "reason": "token_budget_exceeded",
            "chunk_ratio": float(chunk_ratio),
            "context_window": int(context_window),
            "conversation_budget_tokens": int(conversation_budget_tokens),
            "summarization_trigger_tokens": int(summarization_trigger_tokens),
            "historical_conversation_tokens": int(historical_conversation_tokens),
            "selected_turn_ids": selected_ids,
            "start_message_id": start_message_id,
            "end_message_id": end_message_id,
            "selected_token_count": int(selected_token_count),
            "eligible_token_count": int(eligible_token_count),
            "already_summarized_turn_ids_hash": sha256_hex(canonical_json(selected_ids)),
        },
        "created_by": PHASE_5B_CREATED_BY,
    }


def build_summary_generation_job_spec(
    *,
    selection: Any,
    budget: Any,
    primary_provider: str,
    primary_model_name: str,
    secondary_provider: str,
    secondary_model_name: str,
) -> MemoryJobSpec:
    payload = build_summary_generation_payload(
        session_id=selection.session_id,
        selected_turn_ids=selection.selected_turn_ids,
        start_message_id=selection.start_message_id,
        end_message_id=selection.end_message_id,
        selected_token_count=selection.selected_token_count,
        eligible_token_count=selection.eligible_token_count,
        chunk_ratio=selection.chunk_ratio,
        context_window=selection.context_window,
        conversation_budget_tokens=budget.conversation_budget_tokens,
        summarization_trigger_tokens=budget.summarization_trigger_tokens,
        historical_conversation_tokens=budget.historical_conversation_tokens,
        primary_provider=primary_provider,
        primary_model_name=primary_model_name,
        secondary_provider=secondary_provider,
        secondary_model_name=secondary_model_name,
    )
    idempotency_key = make_summary_generation_idempotency_key(
        session_id=selection.session_id,
        selected_turn_ids=selection.selected_turn_ids,
        secondary_provider=payload["models"]["secondary_provider"],
        secondary_model_name=payload["models"]["secondary_model_name"],
    )
    return MemoryJobSpec(
        job_type=_SUMMARY_JOB_TYPE,
        payload=payload,
        idempotency_key=idempotency_key,
        job_id=make_memory_job_id(_SUMMARY_JOB_TYPE, idempotency_key),
        session_id=selection.session_id,
        priority=50,
    )


def enqueue_summary_generation_job(
    *,
    selection: Any,
    budget: Any,
    primary_provider: str,
    primary_model_name: str,
    secondary_provider: str,
    secondary_model_name: str,
    queue: Optional["SQLiteMemoryJobQueue"] = None,
) -> EnqueueResult:
    spec = build_summary_generation_job_spec(
        selection=selection,
        budget=budget,
        primary_provider=primary_provider,
        primary_model_name=primary_model_name,
        secondary_provider=secondary_provider,
        secondary_model_name=secondary_model_name,
    )
    target_queue = queue if queue is not None else SQLiteMemoryJobQueue()
    return target_queue.enqueue_spec(spec)

def extract_latest_turn(state: AgentState) -> Tuple[Optional[str], Optional[str]]:
    messages = list(state.get("messages") or [])
    user_text = next(
        (str(message.content) for message in reversed(messages) if isinstance(message, HumanMessage) and str(message.content).strip()),
        None,
    )
    assistant_text = next(
        (str(message.content) for message in reversed(messages) if isinstance(message, AIMessage) and str(message.content).strip()),
        None,
    )
    return user_text, assistant_text


def _is_hitl_pause(assistant_text: Optional[str]) -> bool:
    return bool(assistant_text and assistant_text.strip().startswith(_HITL_PAUSE_PREFIX))


def is_turn_eligible_for_memory_enqueue(state: AgentState) -> bool:
    approval_status = (state.get("approval_status") or "").upper()
    if approval_status in {"PENDING", "REJECTED"}:
        return False

    user_text, assistant_text = extract_latest_turn(state)
    if not user_text or not assistant_text:
        return False
    if _is_hitl_pause(assistant_text):
        return False

    return True


def _explicit_memory_request(user_text: str) -> bool:
    lowered = user_text.lower()
    return any(
        marker in lowered
        for marker in (
            "remember this",
            "remember that",
            "please remember",
            "don't forget",
            "do not forget",
        )
    )


def _trigger_metadata(state: AgentState, user_text: str) -> Dict[str, Any]:
    return {
        "task_completed": bool(state.get("task_completed", False)),
        "workflow_finished": bool(state.get("workflow_finished", False)),
        "trimming_occurred": bool(state.get("trimming_occurred", False)),
        "explicit_memory_request": _explicit_memory_request(user_text),
        "retrieval_triggered": bool(state.get("retrieval_triggered", False)),
        "tools_used": list(state.get("tools_used") or []),
        "loop_count": int(state.get("loop_count") or 0),
        "approval_status": state.get("approval_status") or "NONE",
    }


def build_post_turn_payload(state: AgentState) -> Optional[Dict[str, Any]]:
    if not is_turn_eligible_for_memory_enqueue(state):
        return None

    user_text, assistant_text = extract_latest_turn(state)
    if not user_text or not assistant_text:
        return None

    from src.harness.llm_router import normalize_provider

    session_id = state.get("session_id") or "default_session"
    provider = normalize_provider(state.get("provider"))
    secondary_provider = normalize_provider(state.get("secondary_provider") or provider)
    payload: Dict[str, Any] = {
        "schema_version": PHASE_3A_PAYLOAD_SCHEMA_VERSION,
        "source": POST_TURN_SOURCE,
        "session_id": session_id,
        "turn": {
            "user_message_id": None,
            "assistant_message_id": None,
            "user_text": user_text,
            "assistant_text": assistant_text,
            "message_count": 2,
            "token_count": int(state.get("token_count") or 0),
        },
        "models": {
            "primary_provider": provider,
            "primary_model_name": state.get("model_name") or "gpt-4o-mini",
            "secondary_provider": secondary_provider,
            "secondary_model_name": state.get("secondary_model_name") or "gpt-4o-mini",
        },
        "trigger_metadata": _trigger_metadata(state, user_text),
        "summary_omitted_turn_ids": list(state.get("summary_omitted_turn_ids") or []),
        "created_by": PHASE_3A_CREATED_BY,
    }
    return payload



def _utc_naive(value: Optional[datetime] = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is not None:
        current = current.astimezone(timezone.utc).replace(tzinfo=None)
    return current


def render_turn_document(payload: Mapping[str, Any]) -> str:
    """Render one conversation turn as the text stored in the cognee session."""
    turn = payload.get("turn") or {}
    metadata = payload.get("trigger_metadata") or {}
    lines = [
        f"User: {str(turn.get('user_text') or '').strip()}",
        f"Assistant: {str(turn.get('assistant_text') or '').strip()}",
    ]
    tools = [str(tool) for tool in metadata.get("tools_used") or []]
    if tools:
        lines.append(f"Tools used to complete the request: {', '.join(tools)}.")
    return "\n".join(lines)


def build_memory_session_write_job_spec(*, user_id: str, session_id: str, text: str) -> MemoryJobSpec:
    """Queue one worth-storing turn for the conversation's cognee session."""
    content = str(text or "").strip()
    if not content:
        raise ValueError("session write requires non-empty text")
    payload: Dict[str, Any] = {
        "schema_version": COGNEE_PAYLOAD_SCHEMA_VERSION,
        "source": POST_TURN_SOURCE,
        "user_id": user_id,
        "session_id": session_id,
        "text": content,
        "created_by": COGNEE_CREATED_BY,
    }
    digest = _short_hash(canonical_json({"user_id": user_id, "session_id": session_id, "text": content}), 16)
    idempotency_key = f"memq:v1:{_SESSION_WRITE_JOB_TYPE}:{_short_hash(f'{user_id}:{session_id}', 12)}:{digest}"
    return MemoryJobSpec(
        job_type=_SESSION_WRITE_JOB_TYPE,
        payload=payload,
        idempotency_key=idempotency_key,
        job_id=make_memory_job_id(_SESSION_WRITE_JOB_TYPE, idempotency_key),
        session_id=session_id,
    )


def build_memory_session_merge_job_spec(
    *,
    user_id: str,
    session_id: str,
    run_at: datetime,
    force: bool = False,
) -> MemoryJobSpec:
    """Queue a session -> main graph merge due at ``run_at``.

    The idempotency key includes the due time, so repeated idle events for the
    same quiet period collapse into one job.
    """
    due = _utc_naive(run_at).replace(microsecond=0)
    payload: Dict[str, Any] = {
        "schema_version": COGNEE_PAYLOAD_SCHEMA_VERSION,
        "source": SESSION_MERGE_SOURCE,
        "user_id": user_id,
        "session_id": session_id,
        "force": bool(force),
        "created_by": COGNEE_CREATED_BY,
    }
    stamp = due.strftime("%Y%m%d%H%M%S") + (":force" if force else "")
    idempotency_key = f"memq:v1:{_SESSION_MERGE_JOB_TYPE}:{_short_hash(f'{user_id}:{session_id}', 12)}:{stamp}"
    return MemoryJobSpec(
        job_type=_SESSION_MERGE_JOB_TYPE,
        payload=payload,
        idempotency_key=idempotency_key,
        job_id=make_memory_job_id(_SESSION_MERGE_JOB_TYPE, idempotency_key),
        session_id=session_id,
        priority=200,
        available_at=due.strftime("%Y-%m-%d %H:%M:%S"),
    )


def build_cognee_ingest_job_spec(
    *,
    documents: Sequence[str],
    source: str,
    user_id: Optional[str] = None,
    priority: int = 100,
) -> MemoryJobSpec:
    """Queue explicit knowledge (API facts/procedures, legacy backfill) for the main graph."""
    normalized = [str(document or "").strip() for document in documents if str(document or "").strip()]
    if not normalized:
        raise ValueError("cognee ingest requires at least one non-empty document")
    payload: Dict[str, Any] = {
        "schema_version": COGNEE_PAYLOAD_SCHEMA_VERSION,
        "source": source,
        "user_id": user_id,
        "documents": normalized,
        "created_by": COGNEE_CREATED_BY,
    }
    digest = _short_hash(canonical_json({"job_type": _COGNEE_INGEST_JOB_TYPE, "user_id": user_id, "documents": normalized}), 16)
    idempotency_key = f"memq:v1:{_COGNEE_INGEST_JOB_TYPE}:{_short_hash(str(user_id or 'default'), 12)}:{digest}"
    return MemoryJobSpec(
        job_type=_COGNEE_INGEST_JOB_TYPE,
        payload=payload,
        idempotency_key=idempotency_key,
        job_id=make_memory_job_id(_COGNEE_INGEST_JOB_TYPE, idempotency_key),
        session_id=None,
        priority=priority,
    )


def enqueue_cognee_ingest(
    *,
    documents: Sequence[str],
    source: str,
    user_id: Optional[str] = None,
    queue: Optional["SQLiteMemoryJobQueue"] = None,
) -> EnqueueResult:
    spec = build_cognee_ingest_job_spec(documents=documents, source=source, user_id=user_id)
    target_queue = queue if queue is not None else SQLiteMemoryJobQueue()
    return target_queue.enqueue_spec(spec)


def build_post_turn_memory_job_specs(state: AgentState) -> List[MemoryJobSpec]:
    """Queue a cognee session write only for turns Jev judged worth storing."""
    decision = state.get("memory_storage_decision") or {}
    if not decision.get("should_store"):
        return []
    from src.memory.cognee_memory import get_cognee_memory

    config = get_cognee_memory().config
    if not (config.enabled and config.storage_enabled):
        return []
    base_payload = build_post_turn_payload(state)
    if base_payload is None:
        return []
    return [
        build_memory_session_write_job_spec(
            user_id=str(state.get("user_id") or config.user_id),
            session_id=str(base_payload["session_id"]),
            text=render_turn_document(base_payload),
        )
    ]

class SQLiteMemoryJobQueue:
    def __init__(self, repository: Any = None, config: Optional[QueueConfig] = None):
        if repository is None:
            from src.memory.job_repository import MemoryJobRepository

            repository = MemoryJobRepository()
        self.repository = repository
        self.config = config if config is not None else load_memory_config().queue

    def enqueue(self, job_type: MemoryJobType, payload: Dict[str, Any], idempotency_key: str) -> str:
        spec = MemoryJobSpec(
            job_type=job_type,
            payload=payload,
            idempotency_key=idempotency_key,
            job_id=make_memory_job_id(job_type, idempotency_key),
            session_id=str(payload.get("session_id")) if payload.get("session_id") else None,
        )
        return self.enqueue_spec(spec).job_id

    def enqueue_spec(self, spec: MemoryJobSpec) -> EnqueueResult:
        if not self.config.queue_persistence_enabled:
            return EnqueueResult(
                job_id=spec.job_id,
                idempotency_key=spec.idempotency_key,
                inserted=False,
                status=MEMORY_JOB_STATUS_QUEUED,
            )
        return self.repository.enqueue(spec, max_attempts=self.config.retry_limit)

    def enqueue_many(self, specs: Sequence[MemoryJobSpec]) -> List[EnqueueResult]:
        return [self.enqueue_spec(spec) for spec in specs]


def enqueue_post_turn_memory_jobs(
    state: AgentState,
    queue: Optional[SQLiteMemoryJobQueue] = None,
) -> List[EnqueueResult]:
    specs = build_post_turn_memory_job_specs(state)
    if not specs:
        return []
    target_queue = queue if queue is not None else SQLiteMemoryJobQueue()
    return target_queue.enqueue_many(specs)











