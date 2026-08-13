import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from src.db import get_connection
from src.memory.episode_store import StructuredEpisodeRecord, StructuredEpisodeRepository
from src.memory.semantic_candidates import PendingFactCandidateRecord, PendingFactCandidateStore
from src.memory.semantic_store import SemanticFactStore, SemanticFactWrite


SEMANTIC_CONSOLIDATION_SCHEMA_VERSION = 1
EPISODE_TRIGGER_THRESHOLD = 10
PENDING_CANDIDATE_TRIGGER_THRESHOLD = 100
DEFAULT_CANDIDATE_BATCH_SIZE = 100
DEFAULT_RECENT_EPISODE_LIMIT = 10
DEFAULT_CURRENT_MEMORY_LIMIT = 50


@dataclass(frozen=True)
class SemanticConsolidationConfig:
    episode_trigger_threshold: int = EPISODE_TRIGGER_THRESHOLD
    pending_candidate_trigger_threshold: int = PENDING_CANDIDATE_TRIGGER_THRESHOLD
    candidate_batch_size: int = DEFAULT_CANDIDATE_BATCH_SIZE
    recent_episode_limit: int = DEFAULT_RECENT_EPISODE_LIMIT
    current_memory_limit: int = DEFAULT_CURRENT_MEMORY_LIMIT


@dataclass(frozen=True)
class SemanticConsolidationTrigger:
    session_id: str
    trigger_type: str
    should_enqueue: bool
    reason: str
    window_key: str
    episode_count: int = 0
    pending_candidate_count: int = 0
    maintenance_date: Optional[str] = None


@dataclass(frozen=True)
class SemanticConsolidationBatch:
    session_id: str
    trigger_type: str
    candidate_ids: List[str]
    episode_ids: List[str]
    semantic_fact_ids: List[str]
    batch_key: str


@dataclass(frozen=True)
class ProposedSemanticFact:
    fact: str
    category: str
    confidence: float
    source_candidate_ids: List[str]
    source_episode_ids: List[str] = field(default_factory=list)
    rationale: str = ""


@dataclass(frozen=True)
class ConsolidationOutcome:
    status: str
    promoted_candidate_ids: List[str]
    discarded_candidate_ids: List[str]
    deferred_candidate_ids: List[str]
    failed_candidate_ids: List[str]
    fact_ids: List[str]
    metrics: Dict[str, Any]


@dataclass(frozen=True)
class ConsolidationRunRecord:
    id: str
    consolidation_type: str
    trigger_type: str
    status: str
    input_refs: Dict[str, Any]
    output_refs: Dict[str, Any]
    metrics: Dict[str, Any]
    error_message: Optional[str]
    source_job_id: Optional[str]
    started_at: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _parse_json_object(value: Any) -> Dict[str, Any]:
    if value is None or value == "":
        return {}
    try:
        parsed = json.loads(str(value))
    except Exception:
        return {}
    return dict(parsed) if isinstance(parsed, Mapping) else {}


def _normalize_non_empty(value: Any, field: str) -> str:
    normalized = re.sub(r"\s+", " ", str(value or "")).strip()
    if not normalized:
        raise ValueError(f"{field} must be non-empty")
    return normalized


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


def _stable_window_key(prefix: str, session_id: str, values: Sequence[str]) -> str:
    payload = {"prefix": prefix, "session_id": session_id, "values": [str(value) for value in values]}
    import hashlib

    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()[:16]


def trigger_for_episode_count(
    session_id: str,
    episode_count: int,
    *,
    threshold: int = EPISODE_TRIGGER_THRESHOLD,
) -> SemanticConsolidationTrigger:
    should_enqueue = int(episode_count) >= int(threshold)
    return SemanticConsolidationTrigger(
        session_id=session_id,
        trigger_type="structured_episode_threshold",
        should_enqueue=should_enqueue,
        reason="10_structured_episodes" if should_enqueue else "below_episode_threshold",
        window_key=f"episodes:{session_id}:{episode_count // max(1, threshold)}",
        episode_count=int(episode_count),
    )


def trigger_for_pending_candidate_count(
    session_id: str,
    pending_candidate_count: int,
    *,
    threshold: int = PENDING_CANDIDATE_TRIGGER_THRESHOLD,
) -> SemanticConsolidationTrigger:
    should_enqueue = int(pending_candidate_count) >= int(threshold)
    return SemanticConsolidationTrigger(
        session_id=session_id,
        trigger_type="pending_candidate_threshold",
        should_enqueue=should_enqueue,
        reason="100_pending_candidates" if should_enqueue else "below_candidate_threshold",
        window_key=f"candidates:{session_id}:{pending_candidate_count // max(1, threshold)}",
        pending_candidate_count=int(pending_candidate_count),
    )


def trigger_for_daily_idle(session_id: str, maintenance_date: str) -> SemanticConsolidationTrigger:
    date_key = _normalize_non_empty(maintenance_date, "maintenance_date")
    return SemanticConsolidationTrigger(
        session_id=session_id,
        trigger_type="daily_idle",
        should_enqueue=True,
        reason="daily_idle_maintenance",
        window_key=f"daily:{session_id}:{date_key}",
        maintenance_date=date_key,
    )


def trigger_for_manual(session_id: str, reason: str = "manual") -> SemanticConsolidationTrigger:
    normalized_reason = _normalize_non_empty(reason, "reason")
    return SemanticConsolidationTrigger(
        session_id=session_id,
        trigger_type="manual",
        should_enqueue=True,
        reason=normalized_reason,
        window_key=f"manual:{session_id}:{normalized_reason}",
    )


class ConsolidationRunRepository:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path

    def create_run(
        self,
        *,
        run_id: str,
        trigger_type: str,
        input_refs: Mapping[str, Any],
        source_job_id: Optional[str] = None,
    ) -> ConsolidationRunRecord:
        existing = self.get_by_id(run_id)
        if existing is not None:
            return existing
        if source_job_id:
            by_job = self.get_by_source_job_id(source_job_id)
            if by_job is not None:
                return by_job

        conn = get_connection(self.db_path)
        try:
            conn.execute(
                """
                INSERT INTO consolidation_runs (
                    id,
                    consolidation_type,
                    trigger_type,
                    status,
                    input_refs_json,
                    output_refs_json,
                    metrics_json,
                    source_job_id,
                    started_at,
                    created_at,
                    updated_at
                ) VALUES (?, 'semantic', ?, 'RUNNING', ?, ?, ?, ?, datetime('now'), datetime('now'), datetime('now'))
                """,
                (run_id, trigger_type, _canonical_json(dict(input_refs)), "{}", "{}", source_job_id),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        record = self.get_by_id(run_id)
        if record is None:
            raise RuntimeError("Consolidation run could not be read after insert")
        return record

    def get_by_id(self, run_id: str) -> Optional[ConsolidationRunRecord]:
        conn = get_connection(self.db_path)
        try:
            row = conn.execute("SELECT * FROM consolidation_runs WHERE id = ?", (run_id,)).fetchone()
            return self._row_to_record(row) if row is not None else None
        finally:
            conn.close()

    def get_by_source_job_id(self, source_job_id: str) -> Optional[ConsolidationRunRecord]:
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                """
                SELECT * FROM consolidation_runs
                WHERE source_job_id = ?
                ORDER BY created_at ASC, id ASC
                LIMIT 1
                """,
                (source_job_id,),
            ).fetchone()
            return self._row_to_record(row) if row is not None else None
        finally:
            conn.close()

    def mark_finished(
        self,
        run_id: str,
        *,
        status: str,
        output_refs: Optional[Mapping[str, Any]] = None,
        metrics: Optional[Mapping[str, Any]] = None,
        error_message: Optional[str] = None,
    ) -> ConsolidationRunRecord:
        if status not in {"SUCCEEDED", "FAILED", "PARTIAL", "CANCELLED"}:
            raise ValueError("status must be a terminal consolidation run status")
        conn = get_connection(self.db_path)
        try:
            conn.execute(
                """
                UPDATE consolidation_runs
                SET status = ?,
                    output_refs_json = ?,
                    metrics_json = ?,
                    error_message = ?,
                    completed_at = datetime('now'),
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                (
                    status,
                    _canonical_json(dict(output_refs or {})),
                    _canonical_json(dict(metrics or {})),
                    error_message,
                    run_id,
                ),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        record = self.get_by_id(run_id)
        if record is None:
            raise RuntimeError("Consolidation run could not be read after update")
        return record

    @staticmethod
    def _row_to_record(row: Any) -> ConsolidationRunRecord:
        return ConsolidationRunRecord(
            id=str(row["id"]),
            consolidation_type=str(row["consolidation_type"]),
            trigger_type=str(row["trigger_type"]),
            status=str(row["status"]),
            input_refs=_parse_json_object(row["input_refs_json"]),
            output_refs=_parse_json_object(row["output_refs_json"]),
            metrics=_parse_json_object(row["metrics_json"]),
            error_message=row["error_message"],
            source_job_id=row["source_job_id"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )


class SemanticConsolidationService:
    def __init__(
        self,
        *,
        db_path: Optional[Path] = None,
        memory_path: Optional[Path] = None,
        config: Optional[SemanticConsolidationConfig] = None,
        candidate_store: Optional[PendingFactCandidateStore] = None,
        episode_repository: Optional[StructuredEpisodeRepository] = None,
        fact_store: Optional[SemanticFactStore] = None,
        run_repository: Optional[ConsolidationRunRepository] = None,
    ):
        self.db_path = db_path
        self.memory_path = memory_path
        self.config = config or SemanticConsolidationConfig()
        self.candidate_store = candidate_store or PendingFactCandidateStore(db_path=db_path)
        self.episode_repository = episode_repository or StructuredEpisodeRepository(db_path=db_path)
        self.fact_store = fact_store or SemanticFactStore(db_path=db_path, memory_path=memory_path)
        self.run_repository = run_repository or ConsolidationRunRepository(db_path=db_path)

    def evaluate_triggers(self, session_id: str, *, maintenance_date: Optional[str] = None) -> List[SemanticConsolidationTrigger]:
        normalized_session_id = _normalize_non_empty(session_id, "session_id")
        episode_count = self.episode_repository.count_by_session(normalized_session_id)
        pending_count = self.candidate_store.count_by_session(normalized_session_id, status="PENDING")
        triggers = [
            trigger_for_episode_count(
                normalized_session_id,
                episode_count,
                threshold=self.config.episode_trigger_threshold,
            ),
            trigger_for_pending_candidate_count(
                normalized_session_id,
                pending_count,
                threshold=self.config.pending_candidate_trigger_threshold,
            ),
        ]
        if maintenance_date is not None:
            triggers.append(trigger_for_daily_idle(normalized_session_id, maintenance_date))
        return triggers

    def build_batch(self, payload: Mapping[str, Any]) -> SemanticConsolidationBatch:
        consolidation = payload.get("semantic_consolidation")
        if not isinstance(consolidation, Mapping):
            raise ValueError("payload is missing semantic_consolidation object")
        session_id = _normalize_non_empty(payload.get("session_id"), "session_id")
        trigger_type = _normalize_non_empty(consolidation.get("trigger_type"), "trigger_type")
        batch_size = max(1, int(consolidation.get("candidate_batch_size") or self.config.candidate_batch_size))
        recent_episode_limit = max(1, int(consolidation.get("recent_episode_limit") or self.config.recent_episode_limit))
        memory_limit = max(1, int(consolidation.get("current_memory_limit") or self.config.current_memory_limit))

        candidate_ids = [str(value) for value in consolidation.get("candidate_ids") or [] if str(value).strip()]
        if not candidate_ids:
            candidates = self.candidate_store.list_by_session(session_id, status="PENDING", limit=batch_size)
            candidate_ids = [candidate.id for candidate in reversed(candidates)]
        else:
            candidate_ids = candidate_ids[:batch_size]

        episode_ids = [str(value) for value in consolidation.get("episode_ids") or [] if str(value).strip()]
        if not episode_ids:
            episodes = self.episode_repository.list_by_session(
                session_id,
                newest_first=True,
                limit=recent_episode_limit,
            )
            episode_ids = [episode.id for episode in episodes]
        else:
            episode_ids = episode_ids[:recent_episode_limit]

        semantic_fact_ids = [str(fact.id) for fact in self.fact_store.list_facts()[:memory_limit]]
        batch_key = _stable_window_key(
            "semantic_consolidation",
            session_id,
            candidate_ids + episode_ids + semantic_fact_ids,
        )
        return SemanticConsolidationBatch(
            session_id=session_id,
            trigger_type=trigger_type,
            candidate_ids=candidate_ids,
            episode_ids=episode_ids,
            semantic_fact_ids=semantic_fact_ids,
            batch_key=batch_key,
        )

    def create_run(
        self,
        payload: Mapping[str, Any],
        batch: SemanticConsolidationBatch,
        *,
        source_job_id: Optional[str],
    ) -> ConsolidationRunRecord:
        consolidation = payload.get("semantic_consolidation") if isinstance(payload.get("semantic_consolidation"), Mapping) else {}
        run_id = str(consolidation.get("run_id") or f"semantic_consolidation_{batch.batch_key}")
        return self.run_repository.create_run(
            run_id=run_id,
            trigger_type=batch.trigger_type,
            input_refs={
                "session_id": batch.session_id,
                "candidate_ids": batch.candidate_ids,
                "episode_ids": batch.episode_ids,
                "semantic_fact_ids": batch.semantic_fact_ids,
                "batch_key": batch.batch_key,
            },
            source_job_id=source_job_id,
        )

    def claim_candidates(self, batch: SemanticConsolidationBatch, run_id: str) -> List[PendingFactCandidateRecord]:
        return self.candidate_store.claim_pending_batch(
            session_id=batch.session_id,
            candidate_ids=batch.candidate_ids,
            batch_id=run_id,
            limit=len(batch.candidate_ids) or self.config.candidate_batch_size,
            metadata_update={"consolidation_run_id": run_id},
        )

    def build_prompt(
        self,
        *,
        candidates: Sequence[PendingFactCandidateRecord],
        episodes: Sequence[StructuredEpisodeRecord],
    ) -> str:
        candidate_payload = [
            {
                "id": candidate.id,
                "fact": candidate.fact,
                "category": candidate.category,
                "confidence": candidate.confidence,
                "source_episode_id": candidate.source_episode_id,
            }
            for candidate in candidates
        ]
        episode_payload = [
            {
                "id": episode.id,
                "title": episode.title,
                "summary": episode.summary,
                "topics": episode.topics,
                "importance": episode.importance,
            }
            for episode in episodes
        ]
        facts = [
            {"id": str(fact.id), "category": fact.category, "fact": fact.fact_text, "confidence": fact.confidence}
            for fact in self.fact_store.list_facts()[: self.config.current_memory_limit]
        ]
        return (
            "Consolidate pending semantic memory candidates. Return only JSON with keys promote, discard, and defer. "
            "Promoted items must include fact, category, confidence, source_candidate_ids, source_episode_ids, and rationale. "
            "Do not make trigger or dedup decisions; permanent writes will pass through a separate dedup service.\n\n"
            f"Pending candidates: {_canonical_json(candidate_payload)}\n"
            f"Structured episodes: {_canonical_json(episode_payload)}\n"
            f"Current semantic facts: {_canonical_json(facts)}"
        )

    def parse_llm_output(self, text: str) -> Dict[str, Any]:
        parsed = _extract_json_value(text)
        if not isinstance(parsed, Mapping):
            raise ValueError("semantic consolidation output must be a JSON object")
        promote = parsed.get("promote", [])
        discard = parsed.get("discard", [])
        defer = parsed.get("defer", [])
        if not isinstance(promote, list) or not isinstance(discard, list) or not isinstance(defer, list):
            raise ValueError("promote, discard, and defer must be arrays")
        return {"promote": promote, "discard": discard, "defer": defer}

    def parse_proposals(self, output: Mapping[str, Any]) -> tuple[List[ProposedSemanticFact], List[str], List[str]]:
        proposals: List[ProposedSemanticFact] = []
        for item in output.get("promote", []):
            if not isinstance(item, Mapping):
                continue
            fact = str(item.get("fact") or "").strip()
            category = str(item.get("category") or "general").strip()
            if not fact or not category:
                continue
            try:
                confidence = float(item.get("confidence", 0.7))
            except (TypeError, ValueError):
                continue
            if confidence < 0 or confidence > 1:
                continue
            candidate_ids = [str(value) for value in item.get("source_candidate_ids") or [] if str(value).strip()]
            episode_ids = [str(value) for value in item.get("source_episode_ids") or [] if str(value).strip()]
            proposals.append(
                ProposedSemanticFact(
                    fact=fact,
                    category=category,
                    confidence=confidence,
                    source_candidate_ids=candidate_ids,
                    source_episode_ids=episode_ids,
                    rationale=str(item.get("rationale") or ""),
                )
            )
        return proposals, _extract_id_list(output.get("discard", [])), _extract_id_list(output.get("defer", []))

    def apply_output(
        self,
        *,
        run_id: str,
        source_job_id: str,
        payload: Mapping[str, Any],
        claimed_candidates: Sequence[PendingFactCandidateRecord],
        output: Mapping[str, Any],
    ) -> ConsolidationOutcome:
        claimed_ids = {candidate.id for candidate in claimed_candidates}
        proposals, discard_ids, defer_ids = self.parse_proposals(output)
        promoted_ids: set[str] = set()
        failed_ids: set[str] = set()
        fact_ids: List[str] = []

        for proposal in proposals:
            referenced_ids = {candidate_id for candidate_id in proposal.source_candidate_ids if candidate_id in claimed_ids}
            if not referenced_ids:
                continue
            try:
                record = self.fact_store.add_explicit_fact(
                    SemanticFactWrite(
                        category=proposal.category,
                        fact_text=proposal.fact,
                        source="semantic_consolidation",
                        confidence=proposal.confidence,
                    ),
                    candidate_id=sorted(referenced_ids)[0],
                    source_job_id=source_job_id,
                    llm_route_payload=payload,
                )
                fact_ids.append(str(record.id))
                self.candidate_store.update_status_many(
                    sorted(referenced_ids),
                    "PROMOTED",
                    metadata_update={
                        "consolidation_run_id": run_id,
                        "promoted_fact_id": str(record.id),
                        "rationale": proposal.rationale,
                        "source_episode_ids": proposal.source_episode_ids,
                    },
                    processed=True,
                )
                promoted_ids.update(referenced_ids)
            except Exception as exc:
                self.candidate_store.update_status_many(
                    sorted(referenced_ids),
                    "FAILED",
                    metadata_update={"consolidation_run_id": run_id, "error_type": type(exc).__name__},
                    processed=True,
                )
                failed_ids.update(referenced_ids)

        discard_ids = sorted({candidate_id for candidate_id in discard_ids if candidate_id in claimed_ids and candidate_id not in promoted_ids and candidate_id not in failed_ids})
        defer_ids = sorted({candidate_id for candidate_id in defer_ids if candidate_id in claimed_ids and candidate_id not in promoted_ids and candidate_id not in failed_ids and candidate_id not in set(discard_ids)})
        unreferenced = sorted(claimed_ids - promoted_ids - failed_ids - set(discard_ids) - set(defer_ids))

        if discard_ids:
            self.candidate_store.update_status_many(
                discard_ids,
                "DISCARDED",
                metadata_update={"consolidation_run_id": run_id},
                processed=True,
            )
        deferred_all = sorted(set(defer_ids) | set(unreferenced))
        if deferred_all:
            self.candidate_store.update_status_many(
                deferred_all,
                "DEFERRED",
                metadata_update={"consolidation_run_id": run_id, "reason": "deferred_or_unreferenced"},
                processed=True,
            )

        status = "PARTIAL" if failed_ids else "SUCCEEDED"
        metrics = {
            "claimed_candidate_count": len(claimed_candidates),
            "promoted_candidate_count": len(promoted_ids),
            "discarded_candidate_count": len(discard_ids),
            "deferred_candidate_count": len(deferred_all),
            "failed_candidate_count": len(failed_ids),
            "fact_count": len(fact_ids),
        }
        return ConsolidationOutcome(
            status=status,
            promoted_candidate_ids=sorted(promoted_ids),
            discarded_candidate_ids=discard_ids,
            deferred_candidate_ids=deferred_all,
            failed_candidate_ids=sorted(failed_ids),
            fact_ids=fact_ids,
            metrics=metrics,
        )

    def finish_run(self, run_id: str, outcome: ConsolidationOutcome) -> ConsolidationRunRecord:
        return self.run_repository.mark_finished(
            run_id,
            status=outcome.status,
            output_refs={
                "promoted_candidate_ids": outcome.promoted_candidate_ids,
                "discarded_candidate_ids": outcome.discarded_candidate_ids,
                "deferred_candidate_ids": outcome.deferred_candidate_ids,
                "failed_candidate_ids": outcome.failed_candidate_ids,
                "fact_ids": outcome.fact_ids,
            },
            metrics=outcome.metrics,
        )

    def fail_run(self, run_id: str, message: str, *, candidates_to_release: Sequence[str] = ()) -> ConsolidationRunRecord:
        if candidates_to_release:
            self.candidate_store.update_status_many(
                candidates_to_release,
                "PENDING",
                metadata_update={"consolidation_run_id": run_id, "recovery_reason": message},
                processed=False,
            )
        return self.run_repository.mark_finished(run_id, status="FAILED", error_message=message)

    def load_episodes(self, episode_ids: Sequence[str]) -> List[StructuredEpisodeRecord]:
        episodes: List[StructuredEpisodeRecord] = []
        for episode_id in episode_ids:
            episode = self.episode_repository.get_by_id(str(episode_id))
            if episode is not None:
                episodes.append(episode)
        return episodes

    def recover_stale_candidates(self, *, batch_id: Optional[str] = None) -> int:
        return self.candidate_store.recover_stale_in_consolidation(batch_id=batch_id)


def _extract_id_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    ids: List[str] = []
    for item in value:
        if isinstance(item, Mapping):
            raw = item.get("candidate_id") or item.get("id")
        else:
            raw = item
        normalized = str(raw or "").strip()
        if normalized:
            ids.append(normalized)
    return ids
