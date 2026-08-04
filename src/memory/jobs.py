import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from langchain_core.messages import AIMessage, HumanMessage

from src.harness.state import AgentState
from src.memory.config import QueueConfig, load_memory_config
from src.memory.types import MemoryJobType


PHASE_3A_PAYLOAD_SCHEMA_VERSION = 1
PHASE_5B_SUMMARY_PAYLOAD_SCHEMA_VERSION = 1
PHASE_6B_EPISODE_PAYLOAD_SCHEMA_VERSION = 1
PHASE_7C_SEMANTIC_CONSOLIDATION_PAYLOAD_SCHEMA_VERSION = 1
PHASE_8B_PROCEDURAL_CANDIDATE_PAYLOAD_SCHEMA_VERSION = 1
PHASE_8C_SKILL_PROMOTION_PAYLOAD_SCHEMA_VERSION = 1
MEMORY_JOB_STATUS_QUEUED = "QUEUED"
MEMORY_JOB_STATUS_RUNNING = "RUNNING"
MEMORY_JOB_STATUS_RETRYING = "RETRYING"
MEMORY_JOB_STATUS_SUCCEEDED = "SUCCEEDED"
MEMORY_JOB_STATUS_FAILED = "FAILED"
MEMORY_JOB_STATUS_DEAD_LETTERED = "DEAD_LETTERED"
MEMORY_JOB_STATUS_CANCELLED = "CANCELLED"
POST_TURN_SOURCE = "graph.post_turn"
SUMMARY_GENERATION_SOURCE = "graph.short_term_budget"
EPISODE_GENERATION_SOURCE = "graph.episode_detector"
SEMANTIC_CONSOLIDATION_SOURCE = "memory.semantic_consolidation_trigger"
PROCEDURAL_CANDIDATE_GENERATION_SOURCE = "memory.episode_generation"
SKILL_PROMOTION_SOURCE = "memory.procedural_promotion"
PHASE_3A_CREATED_BY = "phase_3a_enqueue"
PHASE_5B_CREATED_BY = "phase_5b_summary_enqueue"
PHASE_6B_CREATED_BY = "phase_6b_episode_enqueue"
PHASE_7C_CREATED_BY = "phase_7c_semantic_consolidation_enqueue"
PHASE_8B_CREATED_BY = "phase_8b_procedural_candidate_enqueue"
PHASE_8C_CREATED_BY = "phase_8c_skill_promotion_enqueue"

_HITL_PAUSE_PREFIX = "[HUMAN APPROVAL REQUIRED"
_SEMANTIC_JOB_TYPE: MemoryJobType = "semantic_candidate_extraction"
_EPISODE_JOB_TYPE: MemoryJobType = "episode_generation"
_SUMMARY_JOB_TYPE: MemoryJobType = "summary_generation"
_SEMANTIC_CONSOLIDATION_JOB_TYPE: MemoryJobType = "semantic_consolidation"
_PROCEDURAL_CANDIDATE_JOB_TYPE: MemoryJobType = "procedural_candidate_generation"
_SKILL_PROMOTION_JOB_TYPE: MemoryJobType = "skill_promotion"


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


def make_post_turn_idempotency_key(job_type: str, payload: Dict[str, Any]) -> str:
    turn = payload.get("turn", {})
    models = payload.get("models", {})
    session_id = str(payload.get("session_id") or "default_session")
    canonical_input = {
        "version": PHASE_3A_PAYLOAD_SCHEMA_VERSION,
        "job_type": job_type,
        "session_id": session_id,
        "user_text_hash": sha256_hex(str(turn.get("user_text") or "")),
        "assistant_text_hash": sha256_hex(str(turn.get("assistant_text") or "")),
        "primary_provider": str(models.get("primary_provider") or "openai"),
        "primary_model_name": str(models.get("primary_model_name") or "gpt-4o-mini"),
        "secondary_provider": str(models.get("secondary_provider") or "openai"),
        "secondary_model_name": str(models.get("secondary_model_name") or "gpt-4o-mini"),
    }
    digest = _short_hash(canonical_json(canonical_input), 16)
    session_hash = _short_hash(session_id, 12)
    return f"memq:v1:{job_type}:{session_hash}:{digest}"


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



def make_episode_generation_idempotency_key(
    *,
    session_id: str,
    turn_ids: Sequence[str],
    trigger_reasons: Sequence[str],
    action: str,
    parent_episode_id: Optional[str],
    secondary_provider: str,
    secondary_model_name: str,
    payload_schema_version: int = PHASE_6B_EPISODE_PAYLOAD_SCHEMA_VERSION,
) -> str:
    canonical_input = {
        "schema_version": payload_schema_version,
        "job_type": _EPISODE_JOB_TYPE,
        "session_id": session_id,
        "turn_ids": [str(turn_id) for turn_id in turn_ids],
        "trigger_reasons": [str(reason) for reason in trigger_reasons],
        "action": str(action),
        "parent_episode_id": parent_episode_id,
        "secondary_provider": str(secondary_provider or "openai"),
        "secondary_model_name": str(secondary_model_name or "gpt-4o-mini"),
    }
    window_hash = _short_hash(canonical_json(canonical_input), 16)
    session_hash = _short_hash(session_id, 12)
    return f"memq:v1:{_EPISODE_JOB_TYPE}:{session_hash}:{window_hash}"

def make_semantic_consolidation_idempotency_key(
    *,
    session_id: str,
    trigger_type: str,
    window_key: str,
    candidate_ids: Sequence[str] = (),
    episode_ids: Sequence[str] = (),
    secondary_provider: str,
    secondary_model_name: str,
    payload_schema_version: int = PHASE_7C_SEMANTIC_CONSOLIDATION_PAYLOAD_SCHEMA_VERSION,
) -> str:
    canonical_input = {
        "schema_version": payload_schema_version,
        "job_type": _SEMANTIC_CONSOLIDATION_JOB_TYPE,
        "session_id": str(session_id),
        "trigger_type": str(trigger_type),
        "window_key": str(window_key),
        "candidate_ids": [str(candidate_id) for candidate_id in candidate_ids],
        "episode_ids": [str(episode_id) for episode_id in episode_ids],
        "secondary_provider": str(secondary_provider or "openai"),
        "secondary_model_name": str(secondary_model_name or "gpt-4o-mini"),
    }
    digest = _short_hash(canonical_json(canonical_input), 16)
    session_hash = _short_hash(str(session_id), 12)
    return f"memq:v1:{_SEMANTIC_CONSOLIDATION_JOB_TYPE}:{session_hash}:{digest}"

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



def build_episode_generation_payload(
    *,
    base_payload: Dict[str, Any],
    detection: Any,
    continuation: Any,
) -> Dict[str, Any]:
    from src.harness.llm_router import normalize_provider

    if not detection.should_enqueue or detection.source_window is None:
        raise ValueError("episode detection result is not enqueueable")

    payload = json.loads(canonical_json(base_payload))
    models = payload.get("models", {})
    primary_provider = normalize_provider(models.get("primary_provider"))
    secondary_provider = normalize_provider(models.get("secondary_provider") or primary_provider)
    primary_model_name = models.get("primary_model_name") or "gpt-4o-mini"
    secondary_model_name = models.get("secondary_model_name") or "gpt-4o-mini"
    trigger_metadata = dict(payload.get("trigger_metadata") or {})
    for reason in (
        "explicit_memory_request",
        "trimming_occurred",
        "idle_timeout",
        "long_conversation",
        "task_completed",
        "workflow_finished",
    ):
        trigger_metadata[reason] = reason in detection.reasons

    source_window = detection.source_window
    payload.update(
        {
            "source": EPISODE_GENERATION_SOURCE,
            "models": {
                "primary_provider": primary_provider,
                "primary_model_name": primary_model_name,
                "secondary_provider": secondary_provider,
                "secondary_model_name": secondary_model_name,
            },
            "trigger_metadata": trigger_metadata,
            "episodic": {
                "schema_version": PHASE_6B_EPISODE_PAYLOAD_SCHEMA_VERSION,
                "trigger_reason": detection.primary_reason,
                "trigger_reasons": list(detection.reasons),
                "source": "post_turn",
                "legacy_episode_backfill": False,
                "source_window": {
                    "turn_ids": list(source_window.turn_ids),
                    "start_message_id": source_window.start_message_id,
                    "end_message_id": source_window.end_message_id,
                    "token_count": int(source_window.token_count),
                    "source_text_mode": source_window.source_text_mode,
                    "summary_block_ids": list(source_window.summary_block_ids),
                    "user_text_hash": source_window.user_text_hash,
                    "assistant_text_hash": source_window.assistant_text_hash,
                },
                "continuation": {
                    "action": continuation.action,
                    "parent_episode_id": continuation.parent_episode_id,
                    "related_episode_ids": list(continuation.related_episode_ids),
                    "score": float(continuation.score),
                    "rationale_code": continuation.rationale_code,
                },
            },
            "created_by": PHASE_6B_CREATED_BY,
        }
    )
    return payload


def build_episode_generation_job_spec(
    *,
    base_payload: Dict[str, Any],
    detection: Any,
    continuation: Any,
) -> Optional[MemoryJobSpec]:
    if not detection.should_enqueue or detection.source_window is None:
        return None
    payload = build_episode_generation_payload(
        base_payload=base_payload,
        detection=detection,
        continuation=continuation,
    )
    models = payload["models"]
    idempotency_key = make_episode_generation_idempotency_key(
        session_id=str(payload["session_id"]),
        turn_ids=detection.source_window.turn_ids,
        trigger_reasons=detection.reasons,
        action=continuation.action,
        parent_episode_id=continuation.parent_episode_id,
        secondary_provider=models["secondary_provider"],
        secondary_model_name=models["secondary_model_name"],
    )
    return MemoryJobSpec(
        job_type=_EPISODE_JOB_TYPE,
        payload=payload,
        idempotency_key=idempotency_key,
        job_id=make_memory_job_id(_EPISODE_JOB_TYPE, idempotency_key),
        session_id=str(payload["session_id"]),
        priority=60,
    )


def make_procedural_candidate_generation_idempotency_key(
    *,
    session_id: str,
    source_episode_ids: Sequence[str],
    source_episode_title: str,
    secondary_provider: str,
    secondary_model_name: str,
    payload_schema_version: int = PHASE_8B_PROCEDURAL_CANDIDATE_PAYLOAD_SCHEMA_VERSION,
) -> str:
    canonical_input = {
        "schema_version": payload_schema_version,
        "job_type": _PROCEDURAL_CANDIDATE_JOB_TYPE,
        "session_id": str(session_id),
        "source_episode_ids": [str(episode_id) for episode_id in source_episode_ids],
        "source_episode_title_hash": sha256_hex(str(source_episode_title or "")),
        "secondary_provider": str(secondary_provider or "openai"),
        "secondary_model_name": str(secondary_model_name or "gpt-4o-mini"),
    }
    digest = _short_hash(canonical_json(canonical_input), 16)
    session_hash = _short_hash(str(session_id), 12)
    return f"memq:v1:{_PROCEDURAL_CANDIDATE_JOB_TYPE}:{session_hash}:{digest}"

def build_semantic_consolidation_payload(
    *,
    session_id: str,
    trigger_type: str,
    window_key: str,
    primary_provider: str,
    primary_model_name: str,
    secondary_provider: str,
    secondary_model_name: str,
    candidate_ids: Sequence[str] = (),
    episode_ids: Sequence[str] = (),
    maintenance_date: Optional[str] = None,
    candidate_batch_size: int = 100,
    recent_episode_limit: int = 10,
    current_memory_limit: int = 50,
) -> Dict[str, Any]:
    from src.harness.llm_router import normalize_provider

    provider = normalize_provider(primary_provider)
    sec_provider = normalize_provider(secondary_provider or primary_provider)
    candidate_id_list = [str(candidate_id) for candidate_id in candidate_ids]
    episode_id_list = [str(episode_id) for episode_id in episode_ids]
    return {
        "schema_version": PHASE_7C_SEMANTIC_CONSOLIDATION_PAYLOAD_SCHEMA_VERSION,
        "source": SEMANTIC_CONSOLIDATION_SOURCE,
        "session_id": str(session_id),
        "models": {
            "primary_provider": provider,
            "primary_model_name": primary_model_name or "gpt-4o-mini",
            "secondary_provider": sec_provider,
            "secondary_model_name": secondary_model_name or "gpt-4o-mini",
        },
        "semantic_consolidation": {
            "schema_version": PHASE_7C_SEMANTIC_CONSOLIDATION_PAYLOAD_SCHEMA_VERSION,
            "trigger_type": str(trigger_type),
            "window_key": str(window_key),
            "candidate_ids": candidate_id_list,
            "episode_ids": episode_id_list,
            "maintenance_date": maintenance_date,
            "candidate_batch_size": int(candidate_batch_size),
            "recent_episode_limit": int(recent_episode_limit),
            "current_memory_limit": int(current_memory_limit),
            "promote_through_dedup_store": True,
        },
        "created_by": PHASE_7C_CREATED_BY,
    }


def build_semantic_consolidation_job_spec(
    *,
    session_id: str,
    trigger_type: str,
    window_key: str,
    primary_provider: str,
    primary_model_name: str,
    secondary_provider: str,
    secondary_model_name: str,
    candidate_ids: Sequence[str] = (),
    episode_ids: Sequence[str] = (),
    maintenance_date: Optional[str] = None,
    candidate_batch_size: int = 100,
    recent_episode_limit: int = 10,
    current_memory_limit: int = 50,
) -> MemoryJobSpec:
    payload = build_semantic_consolidation_payload(
        session_id=session_id,
        trigger_type=trigger_type,
        window_key=window_key,
        primary_provider=primary_provider,
        primary_model_name=primary_model_name,
        secondary_provider=secondary_provider,
        secondary_model_name=secondary_model_name,
        candidate_ids=candidate_ids,
        episode_ids=episode_ids,
        maintenance_date=maintenance_date,
        candidate_batch_size=candidate_batch_size,
        recent_episode_limit=recent_episode_limit,
        current_memory_limit=current_memory_limit,
    )
    models = payload["models"]
    idempotency_key = make_semantic_consolidation_idempotency_key(
        session_id=session_id,
        trigger_type=trigger_type,
        window_key=window_key,
        candidate_ids=candidate_ids,
        episode_ids=episode_ids,
        secondary_provider=models["secondary_provider"],
        secondary_model_name=models["secondary_model_name"],
    )
    return MemoryJobSpec(
        job_type=_SEMANTIC_CONSOLIDATION_JOB_TYPE,
        payload=payload,
        idempotency_key=idempotency_key,
        job_id=make_memory_job_id(_SEMANTIC_CONSOLIDATION_JOB_TYPE, idempotency_key),
        session_id=str(session_id),
        priority=70,
    )


def enqueue_semantic_consolidation_job(
    *,
    session_id: str,
    trigger_type: str,
    window_key: str,
    primary_provider: str,
    primary_model_name: str,
    secondary_provider: str,
    secondary_model_name: str,
    candidate_ids: Sequence[str] = (),
    episode_ids: Sequence[str] = (),
    maintenance_date: Optional[str] = None,
    queue: Optional["SQLiteMemoryJobQueue"] = None,
) -> EnqueueResult:
    spec = build_semantic_consolidation_job_spec(
        session_id=session_id,
        trigger_type=trigger_type,
        window_key=window_key,
        primary_provider=primary_provider,
        primary_model_name=primary_model_name,
        secondary_provider=secondary_provider,
        secondary_model_name=secondary_model_name,
        candidate_ids=candidate_ids,
        episode_ids=episode_ids,
        maintenance_date=maintenance_date,
    )
    target_queue = queue if queue is not None else SQLiteMemoryJobQueue()
    return target_queue.enqueue_spec(spec)

def build_procedural_candidate_generation_payload(
    *,
    session_id: str,
    source_episode_id: str,
    source_episode_title: str,
    source_episode_importance: float,
    primary_provider: str,
    primary_model_name: str,
    secondary_provider: str,
    secondary_model_name: str,
    source_episode_ids: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    from src.harness.llm_router import normalize_provider

    episode_ids = [str(episode_id) for episode_id in (source_episode_ids or [source_episode_id])]
    provider = normalize_provider(primary_provider)
    sec_provider = normalize_provider(secondary_provider or primary_provider)
    return {
        "schema_version": PHASE_8B_PROCEDURAL_CANDIDATE_PAYLOAD_SCHEMA_VERSION,
        "source": PROCEDURAL_CANDIDATE_GENERATION_SOURCE,
        "session_id": str(session_id),
        "models": {
            "primary_provider": provider,
            "primary_model_name": primary_model_name or "gpt-4o-mini",
            "secondary_provider": sec_provider,
            "secondary_model_name": secondary_model_name or "gpt-4o-mini",
        },
        "procedural_candidate_generation": {
            "schema_version": PHASE_8B_PROCEDURAL_CANDIDATE_PAYLOAD_SCHEMA_VERSION,
            "source": "structured_episode",
            "source_episode_id": str(source_episode_id),
            "source_episode_ids": episode_ids,
            "source_episode_title": str(source_episode_title),
            "source_episode_importance": float(source_episode_importance),
            "dedup_required": True,
            "create_skill_files": False,
            "promotion_allowed": False,
        },
        "created_by": PHASE_8B_CREATED_BY,
    }


def build_procedural_candidate_generation_job_spec(
    *,
    session_id: str,
    source_episode_id: str,
    source_episode_title: str,
    source_episode_importance: float,
    primary_provider: str,
    primary_model_name: str,
    secondary_provider: str,
    secondary_model_name: str,
    source_episode_ids: Optional[Sequence[str]] = None,
) -> MemoryJobSpec:
    payload = build_procedural_candidate_generation_payload(
        session_id=session_id,
        source_episode_id=source_episode_id,
        source_episode_title=source_episode_title,
        source_episode_importance=source_episode_importance,
        primary_provider=primary_provider,
        primary_model_name=primary_model_name,
        secondary_provider=secondary_provider,
        secondary_model_name=secondary_model_name,
        source_episode_ids=source_episode_ids,
    )
    models = payload["models"]
    payload_details = payload["procedural_candidate_generation"]
    idempotency_key = make_procedural_candidate_generation_idempotency_key(
        session_id=session_id,
        source_episode_ids=payload_details["source_episode_ids"],
        source_episode_title=source_episode_title,
        secondary_provider=models["secondary_provider"],
        secondary_model_name=models["secondary_model_name"],
    )
    return MemoryJobSpec(
        job_type=_PROCEDURAL_CANDIDATE_JOB_TYPE,
        payload=payload,
        idempotency_key=idempotency_key,
        job_id=make_memory_job_id(_PROCEDURAL_CANDIDATE_JOB_TYPE, idempotency_key),
        session_id=str(session_id),
        priority=80,
    )


def enqueue_procedural_candidate_generation_job(
    *,
    session_id: str,
    source_episode_id: str,
    source_episode_title: str,
    source_episode_importance: float,
    primary_provider: str,
    primary_model_name: str,
    secondary_provider: str,
    secondary_model_name: str,
    source_episode_ids: Optional[Sequence[str]] = None,
    queue: Optional["SQLiteMemoryJobQueue"] = None,
) -> EnqueueResult:
    spec = build_procedural_candidate_generation_job_spec(
        session_id=session_id,
        source_episode_id=source_episode_id,
        source_episode_title=source_episode_title,
        source_episode_importance=source_episode_importance,
        primary_provider=primary_provider,
        primary_model_name=primary_model_name,
        secondary_provider=secondary_provider,
        secondary_model_name=secondary_model_name,
        source_episode_ids=source_episode_ids,
    )
    target_queue = queue if queue is not None else SQLiteMemoryJobQueue()
    return target_queue.enqueue_spec(spec)

def make_skill_promotion_idempotency_key(
    *,
    session_id: str,
    candidate_ids: Optional[Sequence[str]] = None,
    trigger_type: str,
    approval_policy: str = "hitl_required",
    window_key: Optional[str] = None,
    payload_schema_version: int = PHASE_8C_SKILL_PROMOTION_PAYLOAD_SCHEMA_VERSION,
) -> str:
    candidate_id_list = sorted({str(candidate_id) for candidate_id in (candidate_ids or []) if str(candidate_id).strip()})
    canonical_input = {
        "schema_version": payload_schema_version,
        "job_type": _SKILL_PROMOTION_JOB_TYPE,
        "session_id": str(session_id),
        "candidate_ids": candidate_id_list,
        "trigger_type": str(trigger_type),
        "approval_policy": str(approval_policy),
        "window_key": str(window_key or "default"),
    }
    digest = _short_hash(canonical_json(canonical_input), 16)
    session_hash = _short_hash(str(session_id), 12)
    return f"memq:v1:{_SKILL_PROMOTION_JOB_TYPE}:{session_hash}:{digest}"


def build_skill_promotion_payload(
    *,
    session_id: str,
    trigger_type: str,
    candidate_ids: Optional[Sequence[str]] = None,
    max_candidates: int = 10,
    approval_policy: str = "hitl_required",
    window_key: Optional[str] = None,
) -> Dict[str, Any]:
    candidate_id_list = sorted({str(candidate_id) for candidate_id in (candidate_ids or []) if str(candidate_id).strip()})
    return {
        "schema_version": PHASE_8C_SKILL_PROMOTION_PAYLOAD_SCHEMA_VERSION,
        "job_type": _SKILL_PROMOTION_JOB_TYPE,
        "source": SKILL_PROMOTION_SOURCE,
        "session_id": str(session_id),
        "skill_promotion": {
            "schema_version": PHASE_8C_SKILL_PROMOTION_PAYLOAD_SCHEMA_VERSION,
            "trigger_type": str(trigger_type),
            "candidate_ids": candidate_id_list,
            "max_candidates": int(max_candidates),
            "approval_policy": str(approval_policy),
            "window_key": window_key,
            "create_skill_files_before_approval": False,
            "activate_after_approval": True,
            "procedural_consolidation_required": False,
        },
        "created_by": PHASE_8C_CREATED_BY,
    }


def build_skill_promotion_job_spec(
    *,
    session_id: str,
    trigger_type: str,
    candidate_ids: Optional[Sequence[str]] = None,
    max_candidates: int = 10,
    approval_policy: str = "hitl_required",
    window_key: Optional[str] = None,
) -> MemoryJobSpec:
    payload = build_skill_promotion_payload(
        session_id=session_id,
        trigger_type=trigger_type,
        candidate_ids=candidate_ids,
        max_candidates=max_candidates,
        approval_policy=approval_policy,
        window_key=window_key,
    )
    payload_details = payload["skill_promotion"]
    idempotency_key = make_skill_promotion_idempotency_key(
        session_id=session_id,
        candidate_ids=payload_details["candidate_ids"],
        trigger_type=trigger_type,
        approval_policy=approval_policy,
        window_key=window_key,
    )
    return MemoryJobSpec(
        job_type=_SKILL_PROMOTION_JOB_TYPE,
        payload=payload,
        idempotency_key=idempotency_key,
        job_id=make_memory_job_id(_SKILL_PROMOTION_JOB_TYPE, idempotency_key),
        session_id=str(session_id),
        priority=80,
    )


def enqueue_skill_promotion_job(
    *,
    session_id: str,
    trigger_type: str,
    candidate_ids: Optional[Sequence[str]] = None,
    max_candidates: int = 10,
    approval_policy: str = "hitl_required",
    window_key: Optional[str] = None,
    queue: Optional["SQLiteMemoryJobQueue"] = None,
) -> EnqueueResult:
    spec = build_skill_promotion_job_spec(
        session_id=session_id,
        trigger_type=trigger_type,
        candidate_ids=candidate_ids,
        max_candidates=max_candidates,
        approval_policy=approval_policy,
        window_key=window_key,
    )
    target_queue = queue if queue is not None else SQLiteMemoryJobQueue()
    return target_queue.enqueue_spec(spec)
def _build_episode_spec_from_detector(base_payload: Dict[str, Any]) -> Optional[MemoryJobSpec]:
    try:
        from src.memory.episode_continuation import decide_episode_continuation
        from src.memory.episode_detector import detect_episode_trigger
        from src.memory.episode_store import StructuredEpisodeRepository
        from src.memory.summary_blocks import SummaryBlockRepository

        session_id = str(base_payload["session_id"])
        summary_repository = SummaryBlockRepository()
        episode_repository = StructuredEpisodeRepository()
        raw_turns = summary_repository.list_raw_turns(session_id=session_id)
        summary_blocks = summary_repository.list_summary_blocks(session_id=session_id)
        existing_episodes = episode_repository.list_by_session(session_id=session_id)
        detection = detect_episode_trigger(
            state=base_payload,
            raw_turns=raw_turns,
            existing_episodes=existing_episodes,
            summary_blocks=summary_blocks,
        )
        if not detection.should_enqueue or detection.source_window is None:
            return None
        continuation = decide_episode_continuation(
            source_window=detection.source_window,
            raw_turns=raw_turns,
            existing_episodes=existing_episodes,
            summary_blocks=summary_blocks,
        )
        return build_episode_generation_job_spec(
            base_payload=base_payload,
            detection=detection,
            continuation=continuation,
        )
    except Exception:
        return None

def _with_job_payload(base_payload: Dict[str, Any], job_type: MemoryJobType) -> Dict[str, Any]:
    payload = json.loads(canonical_json(base_payload))
    if job_type == "semantic_candidate_extraction":
        payload["semantic"] = {
            "candidate_source": "post_turn",
            "extract_explicit_only": False,
            "legacy_pending_facts_backfill": False,
        }
    elif job_type == "episode_generation":
        metadata = payload.get("trigger_metadata", {})
        reason = "explicit_memory_request"
        if metadata.get("trimming_occurred"):
            reason = "trimming_occurred"
        elif metadata.get("task_completed"):
            reason = "task_completed"
        elif metadata.get("workflow_finished"):
            reason = "workflow_finished"
        payload["episodic"] = {
            "trigger_reason": reason,
            "source": "post_turn",
            "legacy_episode_backfill": False,
        }
    return payload


def _should_enqueue_episode_generation(payload: Dict[str, Any]) -> bool:
    metadata = payload.get("trigger_metadata", {})
    return bool(
        metadata.get("explicit_memory_request")
        or metadata.get("trimming_occurred")
        or metadata.get("task_completed")
        or metadata.get("workflow_finished")
    )


def _build_spec(job_type: MemoryJobType, payload: Dict[str, Any], session_id: str) -> MemoryJobSpec:
    idempotency_key = make_post_turn_idempotency_key(job_type, payload)
    return MemoryJobSpec(
        job_type=job_type,
        payload=payload,
        idempotency_key=idempotency_key,
        job_id=make_memory_job_id(job_type, idempotency_key),
        session_id=session_id,
    )


def build_post_turn_memory_job_specs(state: AgentState) -> List[MemoryJobSpec]:
    base_payload = build_post_turn_payload(state)
    if base_payload is None:
        return []

    session_id = str(base_payload["session_id"])
    specs = [
        _build_spec(
            _SEMANTIC_JOB_TYPE,
            _with_job_payload(base_payload, _SEMANTIC_JOB_TYPE),
            session_id,
        )
    ]

    episode_spec = _build_episode_spec_from_detector(base_payload)
    if episode_spec is not None:
        specs.append(episode_spec)

    return specs

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











