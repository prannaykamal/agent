import json

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Protocol


ALL_MEMORY_JOB_TYPES = (
    "episode_generation",
    "semantic_candidate_extraction",
    "procedural_candidate_generation",
    "semantic_consolidation",
    "procedural_consolidation",
    "skill_promotion",
    "summary_generation",
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



def _extract_json_object(text: str) -> Dict[str, Any]:
    content = str(text or "").strip()
    if content.startswith("```json"):
        content = content[7:].strip()
        if content.endswith("```"):
            content = content[:-3].strip()
    elif content.startswith("```"):
        content = content[3:].strip()
        if content.endswith("```"):
            content = content[:-3].strip()
    parsed = json.loads(content)
    if not isinstance(parsed, dict):
        raise ValueError("Episode LLM output must be a JSON object")
    return parsed


def _list_of_strings(value: Any, default: list[str]) -> list[str]:
    if not isinstance(value, list):
        return list(default)
    normalized = [str(item).strip() for item in value if isinstance(item, str) and str(item).strip()]
    return normalized if normalized else list(default)


def _importance(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.5
    if parsed < 0 or parsed > 1:
        return 0.5
    return parsed




def _extract_json_value(text: str) -> Any:
    content = str(text or "").strip()
    if content.startswith("```json"):
        content = content[7:].strip()
        if content.endswith("```"):
            content = content[:-3].strip()
    elif content.startswith("```"):
        content = content[3:].strip()
        if content.endswith("```"):
            content = content[:-3].strip()
    return json.loads(content)


def _semantic_payload_failure(message: str, *, retryable: bool = False) -> JobHandlerResult:
    return JobHandlerResult(
        success=False,
        retryable=retryable,
        result={
            "handler": "semantic_candidate_extraction",
            "job_type": "semantic_candidate_extraction",
            "processed": False,
            "phase": "7A",
            "message": message,
        },
    )


@dataclass(frozen=True)
class SemanticCandidateExtractionJobHandler:
    job_type: str = "semantic_candidate_extraction"

    def handle(self, job: Mapping[str, Any], payload: Mapping[str, Any]) -> JobHandlerResult:
        if not isinstance(payload, Mapping):
            return _semantic_payload_failure("Payload must be a JSON object")
        if "schema_version" not in payload:
            return _semantic_payload_failure("Payload is missing schema_version")

        semantic_payload = payload.get("semantic") or {}
        if semantic_payload and not isinstance(semantic_payload, Mapping):
            return _semantic_payload_failure("semantic payload must be a JSON object")

        turn = payload.get("turn") or {}
        if turn and not isinstance(turn, Mapping):
            return _semantic_payload_failure("turn payload must be a JSON object")

        user_text = str(turn.get("user_text") or "").strip() if isinstance(turn, Mapping) else ""
        assistant_text = str(turn.get("assistant_text") or "").strip() if isinstance(turn, Mapping) else ""
        if not user_text and not assistant_text:
            return JobHandlerResult(
                success=True,
                result={
                    "handler": self.job_type,
                    "job_type": self.job_type,
                    "processed": False,
                    "phase": "7A",
                    "message": "No turn text available for semantic candidate extraction",
                    "candidate_count": 0,
                    "deterministic_candidate_count": 0,
                    "llm_candidate_count": 0,
                    "llm_available": None,
                },
            )

        from src.memory.semantic_candidates import (
            PendingFactCandidateStore,
            PendingFactCandidateWrite,
            extract_explicit_facts_from_user_text,
        )

        session_id = str(payload.get("session_id") or job.get("session_id") or "default_session")
        job_id = str(job.get("id") or "")
        batch_id = job_id or None
        models = payload.get("models") if isinstance(payload.get("models"), Mapping) else {}
        secondary_provider = str(models.get("secondary_provider") or "") if isinstance(models, Mapping) else ""
        secondary_model_name = str(models.get("secondary_model_name") or "") if isinstance(models, Mapping) else ""
        source_message_id = turn.get("user_message_id") if isinstance(turn, Mapping) else None
        store = PendingFactCandidateStore()

        deterministic_writes: List[PendingFactCandidateWrite] = []
        for fact in extract_explicit_facts_from_user_text(user_text):
            deterministic_writes.append(
                PendingFactCandidateWrite(
                    session_id=session_id,
                    fact=fact.fact_text,
                    category=fact.category,
                    confidence=fact.confidence,
                    explicit=True,
                    source="deterministic_explicit_chat",
                    source_message_id=source_message_id,
                    batch_id=batch_id,
                    metadata={
                        "source_job_id": job_id,
                        "job_type": self.job_type,
                        "model_provider": secondary_provider,
                        "model_name": secondary_model_name,
                        "extraction_method": "deterministic",
                    },
                )
            )

        try:
            deterministic_records = store.add_candidates(deterministic_writes) if deterministic_writes else []
        except Exception as exc:
            return JobHandlerResult(
                success=False,
                retryable=True,
                result={
                    "handler": self.job_type,
                    "job_type": self.job_type,
                    "processed": False,
                    "phase": "7A",
                    "message": "Failed to write deterministic semantic candidates",
                    "error_type": type(exc).__name__,
                },
            )

        route = _resolve_secondary_route(payload)
        if not getattr(route, "available", False) or getattr(route, "llm", None) is None:
            if deterministic_records:
                return JobHandlerResult(
                    success=True,
                    result={
                        "handler": self.job_type,
                        "job_type": self.job_type,
                        "processed": True,
                        "phase": "7A",
                        "message": "Deterministic semantic candidates written; secondary LLM unavailable",
                        "candidate_count": len(deterministic_records),
                        "deterministic_candidate_count": len(deterministic_records),
                        "llm_candidate_count": 0,
                        "llm_available": False,
                    },
                )
            return JobHandlerResult(
                success=False,
                retryable=True,
                result={
                    "handler": self.job_type,
                    "job_type": self.job_type,
                    "processed": False,
                    "phase": "7A",
                    "message": "Secondary LLM unavailable",
                    "candidate_count": 0,
                    "deterministic_candidate_count": 0,
                    "llm_candidate_count": 0,
                    "llm_available": False,
                },
            )

        prompt = (
            "Extract candidate semantic facts from this completed chat turn. "
            "Return only JSON in the form {\"candidates\":[{\"fact\":\"...\",\"category\":\"...\",\"confidence\":0.0,\"rationale\":\"...\"}]}. "
            "Do not deduplicate, consolidate, promote, write permanent memory, create embeddings, or infer skills. "
            "If there are no stable candidate facts, return {\"candidates\":[]} .\n\n"
            f"User: {user_text}\n"
            f"Assistant: {assistant_text}"
        )
        try:
            response = route.llm.invoke(prompt)
            parsed = _extract_json_value(str(getattr(response, "content", response)))
        except Exception as exc:
            return JobHandlerResult(
                success=False,
                retryable=True,
                result={
                    "handler": self.job_type,
                    "job_type": self.job_type,
                    "processed": bool(deterministic_records),
                    "phase": "7A",
                    "message": "Semantic candidate LLM output could not be parsed",
                    "error_type": type(exc).__name__,
                    "deterministic_candidate_count": len(deterministic_records),
                },
            )

        if isinstance(parsed, Mapping):
            raw_candidates = parsed.get("candidates", [])
        elif isinstance(parsed, list):
            raw_candidates = parsed
        else:
            return JobHandlerResult(
                success=False,
                retryable=True,
                result={
                    "handler": self.job_type,
                    "job_type": self.job_type,
                    "processed": bool(deterministic_records),
                    "phase": "7A",
                    "message": "Semantic candidate LLM output must be a JSON object or list",
                    "deterministic_candidate_count": len(deterministic_records),
                },
            )
        if not isinstance(raw_candidates, list):
            raw_candidates = []

        llm_writes: List[PendingFactCandidateWrite] = []
        for index, candidate in enumerate(raw_candidates):
            if not isinstance(candidate, Mapping):
                continue
            fact_text = str(candidate.get("fact") or "").strip()
            if not fact_text:
                continue
            try:
                confidence = float(candidate.get("confidence", 0.5))
            except (TypeError, ValueError):
                continue
            if confidence < 0 or confidence > 1:
                continue
            metadata = {
                "source_job_id": job_id,
                "job_type": self.job_type,
                "model_provider": secondary_provider,
                "model_name": secondary_model_name,
                "extraction_method": "secondary_llm",
                "candidate_index": index,
            }
            if candidate.get("rationale") is not None:
                metadata["rationale"] = str(candidate.get("rationale"))
            llm_writes.append(
                PendingFactCandidateWrite(
                    session_id=session_id,
                    fact=fact_text,
                    category=str(candidate.get("category") or "general"),
                    confidence=confidence,
                    explicit=False,
                    source="secondary_llm_candidate",
                    source_message_id=source_message_id,
                    batch_id=batch_id,
                    metadata=metadata,
                )
            )

        try:
            llm_records = store.add_candidates(llm_writes) if llm_writes else []
        except Exception as exc:
            return JobHandlerResult(
                success=False,
                retryable=True,
                result={
                    "handler": self.job_type,
                    "job_type": self.job_type,
                    "processed": bool(deterministic_records),
                    "phase": "7A",
                    "message": "Failed to write LLM semantic candidates",
                    "error_type": type(exc).__name__,
                    "deterministic_candidate_count": len(deterministic_records),
                },
            )

        return JobHandlerResult(
            success=True,
            result={
                "handler": self.job_type,
                "job_type": self.job_type,
                "processed": bool(deterministic_records or llm_records),
                "phase": "7A",
                "message": "Semantic fact candidates written",
                "candidate_count": len(deterministic_records) + len(llm_records),
                "deterministic_candidate_count": len(deterministic_records),
                "llm_candidate_count": len(llm_records),
                "llm_available": True,
            },
        )
@dataclass(frozen=True)
class SemanticConsolidationJobHandler:
    job_type: str = "semantic_consolidation"

    def handle(self, job: Mapping[str, Any], payload: Mapping[str, Any]) -> JobHandlerResult:
        if not isinstance(payload, Mapping):
            return JobHandlerResult(False, {"handler": self.job_type, "job_type": self.job_type, "processed": False, "phase": "7C", "message": "Payload must be a JSON object"}, retryable=False)
        if payload.get("schema_version") != 1:
            return JobHandlerResult(False, {"handler": self.job_type, "job_type": self.job_type, "processed": False, "phase": "7C", "message": "Payload schema_version must be 1"}, retryable=False)
        consolidation = payload.get("semantic_consolidation")
        if not isinstance(consolidation, Mapping) or consolidation.get("schema_version") != 1:
            return JobHandlerResult(False, {"handler": self.job_type, "job_type": self.job_type, "processed": False, "phase": "7C", "message": "Payload is missing Phase 7C semantic_consolidation object"}, retryable=False)

        from src.memory.semantic_consolidation import SemanticConsolidationService

        job_id = str(job.get("id") or "")
        service = SemanticConsolidationService()
        try:
            batch = service.build_batch(payload)
            run = service.create_run(payload, batch, source_job_id=job_id or None)
            claimed = service.claim_candidates(batch, run.id)
        except Exception as exc:
            return JobHandlerResult(
                success=False,
                retryable=True,
                result={
                    "handler": self.job_type,
                    "job_type": self.job_type,
                    "processed": False,
                    "phase": "7C",
                    "message": "Failed to prepare semantic consolidation batch",
                    "error_type": type(exc).__name__,
                },
            )

        claimed_ids = [candidate.id for candidate in claimed]
        if not claimed_ids:
            try:
                service.run_repository.mark_finished(
                    run.id,
                    status="SUCCEEDED",
                    output_refs={"fact_ids": [], "promoted_candidate_ids": []},
                    metrics={"claimed_candidate_count": 0, "fact_count": 0},
                )
            except Exception:
                pass
            return JobHandlerResult(
                success=True,
                result={
                    "handler": self.job_type,
                    "job_type": self.job_type,
                    "processed": False,
                    "phase": "7C",
                    "message": "No pending candidates available for semantic consolidation",
                    "claimed_candidate_count": 0,
                    "fact_count": 0,
                },
            )

        route = _resolve_secondary_route(payload)
        if not getattr(route, "available", False) or getattr(route, "llm", None) is None:
            try:
                service.fail_run(run.id, "Secondary LLM unavailable", candidates_to_release=claimed_ids)
            except Exception:
                pass
            return JobHandlerResult(
                success=False,
                retryable=True,
                result={
                    "handler": self.job_type,
                    "job_type": self.job_type,
                    "processed": False,
                    "phase": "7C",
                    "message": "Secondary LLM unavailable",
                    "claimed_candidate_count": len(claimed_ids),
                },
            )

        try:
            episodes = service.load_episodes(batch.episode_ids)
            prompt = service.build_prompt(candidates=claimed, episodes=episodes)
            response = route.llm.invoke(prompt)
            parsed = service.parse_llm_output(str(getattr(response, "content", response)))
        except Exception as exc:
            try:
                service.fail_run(run.id, "Semantic consolidation LLM output could not be parsed", candidates_to_release=claimed_ids)
            except Exception:
                pass
            return JobHandlerResult(
                success=False,
                retryable=True,
                result={
                    "handler": self.job_type,
                    "job_type": self.job_type,
                    "processed": False,
                    "phase": "7C",
                    "message": "Semantic consolidation LLM output could not be parsed",
                    "error_type": type(exc).__name__,
                    "claimed_candidate_count": len(claimed_ids),
                },
            )

        try:
            outcome = service.apply_output(
                run_id=run.id,
                source_job_id=job_id,
                payload=payload,
                claimed_candidates=claimed,
                output=parsed,
            )
            service.finish_run(run.id, outcome)
        except Exception as exc:
            try:
                service.fail_run(run.id, "Semantic consolidation failed after LLM output", candidates_to_release=claimed_ids)
            except Exception:
                pass
            return JobHandlerResult(
                success=False,
                retryable=True,
                result={
                    "handler": self.job_type,
                    "job_type": self.job_type,
                    "processed": False,
                    "phase": "7C",
                    "message": "Semantic consolidation failed after LLM output",
                    "error_type": type(exc).__name__,
                    "claimed_candidate_count": len(claimed_ids),
                },
            )

        return JobHandlerResult(
            success=True,
            result={
                "handler": self.job_type,
                "job_type": self.job_type,
                "processed": True,
                "phase": "7C",
                "message": "Semantic consolidation completed",
                "run_id": run.id,
                "run_status": outcome.status,
                "claimed_candidate_count": len(claimed_ids),
                "promoted_candidate_count": len(outcome.promoted_candidate_ids),
                "discarded_candidate_count": len(outcome.discarded_candidate_ids),
                "deferred_candidate_count": len(outcome.deferred_candidate_ids),
                "failed_candidate_count": len(outcome.failed_candidate_ids),
                "fact_count": len(outcome.fact_ids),
            },
        )


@dataclass(frozen=True)
class EpisodeGenerationJobHandler:
    job_type: str = "episode_generation"

    def handle(self, job: Mapping[str, Any], payload: Mapping[str, Any]) -> JobHandlerResult:
        if not isinstance(payload, Mapping):
            return JobHandlerResult(False, {"handler": "episode_generation", "job_type": self.job_type, "processed": False, "phase": "6B", "message": "Payload must be a JSON object"}, retryable=False)
        if "schema_version" not in payload:
            return JobHandlerResult(False, {"handler": "episode_generation", "job_type": self.job_type, "processed": False, "phase": "6B", "message": "Payload is missing schema_version"}, retryable=False)
        episodic = payload.get("episodic")
        if not isinstance(episodic, Mapping) or episodic.get("schema_version") != 1:
            return JobHandlerResult(False, {"handler": "episode_generation", "job_type": self.job_type, "processed": False, "phase": "6B", "message": "Payload is missing Phase 6B episodic object"}, retryable=False)
        source_window = episodic.get("source_window")
        continuation = episodic.get("continuation")
        if not isinstance(source_window, Mapping) or not isinstance(continuation, Mapping):
            return JobHandlerResult(False, {"handler": "episode_generation", "job_type": self.job_type, "processed": False, "phase": "6B", "message": "Payload is missing source window or continuation metadata"}, retryable=False)
        turn_ids = source_window.get("turn_ids")
        if not isinstance(turn_ids, list) or not turn_ids:
            return JobHandlerResult(False, {"handler": "episode_generation", "job_type": self.job_type, "processed": False, "phase": "6B", "message": "episodic.source_window.turn_ids must be a non-empty list"}, retryable=False)
        turn_ids = [str(turn_id) for turn_id in turn_ids]
        action = str(continuation.get("action") or "")
        if action not in {"CREATE", "UPDATE", "MERGE", "SPLIT"}:
            return JobHandlerResult(False, {"handler": "episode_generation", "job_type": self.job_type, "processed": False, "phase": "6B", "message": "continuation.action must be CREATE, UPDATE, MERGE, or SPLIT"}, retryable=False)

        from src.memory.episode_store import StructuredEpisodeRepository, StructuredEpisodeWrite

        session_id = str(payload.get("session_id") or job.get("session_id") or "default_session")
        repository = StructuredEpisodeRepository()
        job_id = str(job.get("id") or "")
        existing = repository.get_by_source_job_id(job_id) if job_id else None
        if existing is not None:
            return JobHandlerResult(True, {"handler": "episode_generation", "job_type": self.job_type, "processed": False, "phase": "6B", "message": "Structured episode already exists for job", "structured_episode_id": existing.id, "action": existing.action})

        from src.memory.summary_blocks import SummaryBlockRepository

        try:
            turns = SummaryBlockRepository().list_raw_turns_by_ids(session_id=session_id, turn_ids=turn_ids)
        except Exception as exc:
            return JobHandlerResult(False, {"handler": "episode_generation", "job_type": self.job_type, "processed": False, "phase": "6B", "message": "Failed to load selected raw turns", "error_type": type(exc).__name__}, retryable=True)
        if [turn.id for turn in turns] != turn_ids:
            return JobHandlerResult(False, {"handler": "episode_generation", "job_type": self.job_type, "processed": False, "phase": "6B", "message": "Selected raw turns were not found"}, retryable=False)

        route = _resolve_secondary_route(payload)
        if not getattr(route, "available", False) or getattr(route, "llm", None) is None:
            return JobHandlerResult(False, {"handler": "episode_generation", "job_type": self.job_type, "processed": False, "phase": "6B", "message": "Secondary LLM unavailable"}, retryable=True)

        turn_text = "\n".join(f"{turn.sender}: {turn.content}" for turn in turns)
        prompt = (
            "Generate structured episodic memory content for these conversation turns. "
            "The deterministic system has already decided that an episode exists and has already chosen the lifecycle action. "
            "Do not decide action, trigger, parent episode, semantic facts, or skills. "
            "Return only JSON with keys: title, summary, participants, goals, decisions, artifacts, topics, importance.\n\n"
            f"Trigger reason: {episodic.get('trigger_reason')}\n"
            f"Deterministic action: {action}\n\n"
            f"Conversation turns:\n{turn_text}"
        )
        try:
            response = route.llm.invoke(prompt)
            parsed = _extract_json_object(str(getattr(response, "content", response)))
        except Exception as exc:
            return JobHandlerResult(False, {"handler": "episode_generation", "job_type": self.job_type, "processed": False, "phase": "6B", "message": "Episode LLM output could not be parsed", "error_type": type(exc).__name__}, retryable=True)

        title = str(parsed.get("title") or "").strip()
        summary = str(parsed.get("summary") or "").strip()
        if not title or not summary:
            return JobHandlerResult(False, {"handler": "episode_generation", "job_type": self.job_type, "processed": False, "phase": "6B", "message": "Episode LLM output is missing title or summary"}, retryable=True)

        try:
            record = repository.append_episode(
                StructuredEpisodeWrite(
                    session_id=session_id,
                    title=title,
                    summary=summary,
                    participants=_list_of_strings(parsed.get("participants"), ["User", "Assistant"]),
                    goals=_list_of_strings(parsed.get("goals"), []),
                    decisions=_list_of_strings(parsed.get("decisions"), []),
                    artifacts=_list_of_strings(parsed.get("artifacts"), []),
                    topics=_list_of_strings(parsed.get("topics"), ["General"]),
                    importance=_importance(parsed.get("importance")),
                    start_message_id=str(source_window.get("start_message_id") or turn_ids[0]),
                    end_message_id=str(source_window.get("end_message_id") or turn_ids[-1]),
                    source="worker.episode_generation",
                    action=action,  # type: ignore[arg-type]
                    parent_episode_id=continuation.get("parent_episode_id"),
                    source_job_id=job_id,
                )
            )
        except Exception as exc:
            return JobHandlerResult(False, {"handler": "episode_generation", "job_type": self.job_type, "processed": False, "phase": "6B", "message": "Failed to append structured episode", "error_type": type(exc).__name__}, retryable=False)

        return JobHandlerResult(
            True,
            {
                "handler": "episode_generation",
                "job_type": self.job_type,
                "processed": True,
                "phase": "6B",
                "message": "Structured episode appended",
                "structured_episode_id": record.id,
                "action": record.action,
                "parent_episode_id": record.parent_episode_id,
                "related_episode_ids": list(continuation.get("related_episode_ids") or []),
                "trigger_reason": episodic.get("trigger_reason"),
            },
        )

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

def build_default_handler_registry() -> Dict[str, MemoryJobHandler]:
    registry = {job_type: NoOpMemoryJobHandler(job_type=job_type) for job_type in ALL_MEMORY_JOB_TYPES}
    registry["semantic_candidate_extraction"] = SemanticCandidateExtractionJobHandler()
    registry["semantic_consolidation"] = SemanticConsolidationJobHandler()
    registry["episode_generation"] = EpisodeGenerationJobHandler()
    registry["summary_generation"] = SummaryGenerationJobHandler()
    return registry








