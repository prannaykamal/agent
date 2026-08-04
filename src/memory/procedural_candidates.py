import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Mapping, Optional, Sequence

from src.db import get_connection
from src.memory.config import load_memory_config


SkillCandidateStatus = Literal[
    "NEW",
    "OBSERVING",
    "READY_FOR_PROMOTION",
    "WAITING_FOR_APPROVAL",
    "PROMOTED",
    "REJECTED",
]

VALID_SKILL_CANDIDATE_STATUSES = {
    "NEW",
    "OBSERVING",
    "READY_FOR_PROMOTION",
    "WAITING_FOR_APPROVAL",
    "PROMOTED",
    "REJECTED",
}

TERMINAL_OR_APPROVAL_STATUSES = {"WAITING_FOR_APPROVAL", "PROMOTED", "REJECTED"}


class SkillCandidateValidationError(ValueError):
    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message
        super().__init__(f"{field}: {message}")


@dataclass(frozen=True)
class SkillWorkflowStep:
    order: int
    instruction: str
    tool_hint: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"order": int(self.order), "instruction": self.instruction, "tool_hint": self.tool_hint}


@dataclass(frozen=True)
class SkillCandidateWrite:
    title: str
    description: str
    trigger_description: str
    workflow: Sequence[SkillWorkflowStep | Mapping[str, Any]]
    preferred_tools: Sequence[str] = field(default_factory=list)
    tags: Sequence[str] = field(default_factory=list)
    workflow_category: Optional[str] = None
    confidence: float = 0.5
    source_episode_ids: Sequence[str] = field(default_factory=list)
    status: SkillCandidateStatus = "NEW"
    dedup_group_id: Optional[str] = None
    source_job_id: Optional[str] = None
    id: Optional[str] = None


@dataclass(frozen=True)
class SkillCandidateRecord:
    id: str
    title: str
    description: str
    trigger_description: str
    workflow: List[Dict[str, Any]]
    preferred_tools: List[str]
    tags: List[str]
    workflow_category: Optional[str]
    confidence: float
    occurrences: int
    source_episode_ids: List[str]
    status: SkillCandidateStatus
    dedup_group_id: Optional[str]
    source_job_id: Optional[str]
    created_at: str
    updated_at: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "trigger_description": self.trigger_description,
            "workflow": list(self.workflow),
            "preferred_tools": list(self.preferred_tools),
            "tags": list(self.tags),
            "workflow_category": self.workflow_category,
            "confidence": self.confidence,
            "occurrences": self.occurrences,
            "source_episode_ids": list(self.source_episode_ids),
            "status": self.status,
            "dedup_group_id": self.dedup_group_id,
            "source_job_id": self.source_job_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def parse_json_list(value: Any) -> List[Any]:
    if value is None or value == "":
        return []
    try:
        parsed = json.loads(str(value))
    except Exception:
        return []
    return parsed if isinstance(parsed, list) else []


def _hash(value: Any, length: int = 16) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()[:length]


def _normalize_text(value: Any, field: str) -> str:
    normalized = re.sub(r"\s+", " ", str(value or "")).strip()
    if not normalized:
        raise SkillCandidateValidationError(field, "must be non-empty")
    return normalized


def _normalize_optional_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    normalized = re.sub(r"\s+", " ", str(value or "")).strip()
    return normalized or None


def _normalize_string_list(values: Sequence[str], field: str, *, require_non_empty: bool = False) -> List[str]:
    if isinstance(values, str) or not isinstance(values, Sequence):
        raise SkillCandidateValidationError(field, "must be a list of strings")
    normalized = sorted({re.sub(r"\s+", " ", str(value)).strip() for value in values if str(value).strip()})
    if require_non_empty and not normalized:
        raise SkillCandidateValidationError(field, "must contain at least one value")
    return normalized


def _normalize_workflow(workflow: Sequence[SkillWorkflowStep | Mapping[str, Any]]) -> List[Dict[str, Any]]:
    if isinstance(workflow, str) or not isinstance(workflow, Sequence) or not workflow:
        raise SkillCandidateValidationError("workflow", "must contain at least one step")
    normalized: List[Dict[str, Any]] = []
    for index, raw in enumerate(workflow):
        if isinstance(raw, SkillWorkflowStep):
            item = raw.to_dict()
        elif isinstance(raw, Mapping):
            item = dict(raw)
        else:
            raise SkillCandidateValidationError("workflow", f"step {index} must be an object")
        try:
            order = int(item.get("order", index + 1))
        except (TypeError, ValueError) as exc:
            raise SkillCandidateValidationError("workflow", f"step {index} order must be an integer") from exc
        if order <= 0:
            raise SkillCandidateValidationError("workflow", f"step {index} order must be positive")
        instruction = _normalize_text(item.get("instruction"), "workflow")
        tool_hint = _normalize_optional_text(item.get("tool_hint"))
        normalized.append({"order": order, "instruction": instruction, "tool_hint": tool_hint})
    return sorted(normalized, key=lambda step: (int(step["order"]), str(step["instruction"])))


def _status_for(occurrences: int, confidence: float, current_status: Optional[str] = None) -> SkillCandidateStatus:
    if current_status in TERMINAL_OR_APPROVAL_STATUSES:
        return current_status  # type: ignore[return-value]
    if current_status == "READY_FOR_PROMOTION":
        return "READY_FOR_PROMOTION"
    try:
        procedural = load_memory_config().procedural
        occurrence_threshold = procedural.promotion_occurrence_threshold
        confidence_threshold = procedural.promotion_confidence_threshold
    except Exception:
        occurrence_threshold = 3
        confidence_threshold = 0.90
    if int(occurrences) >= int(occurrence_threshold) and float(confidence) >= float(confidence_threshold):
        return "READY_FOR_PROMOTION"
    if int(occurrences) > 1:
        return "OBSERVING"
    return "NEW"


def _merge_unique(*groups: Sequence[str]) -> List[str]:
    return sorted({str(value).strip() for group in groups for value in group if str(value).strip()})


def make_skill_candidate_id(write: SkillCandidateWrite) -> str:
    source_job_id = _normalize_optional_text(write.source_job_id)
    if source_job_id:
        return f"skillcand_job_{_hash(source_job_id, 18)}"
    payload = {
        "title": str(write.title).lower().strip(),
        "trigger": str(write.trigger_description).lower().strip(),
        "category": str(write.workflow_category or "").lower().strip(),
        "source_episode_ids": [str(value) for value in write.source_episode_ids],
    }
    return f"skillcand_{_hash(payload, 18)}"


def validate_skill_candidate_write(write: SkillCandidateWrite) -> SkillCandidateWrite:
    confidence = float(write.confidence)
    if confidence < 0 or confidence > 1:
        raise SkillCandidateValidationError("confidence", "must be between 0 and 1")
    status = str(write.status)
    if status not in VALID_SKILL_CANDIDATE_STATUSES:
        raise SkillCandidateValidationError("status", "must be valid")
    return SkillCandidateWrite(
        title=_normalize_text(write.title, "title"),
        description=_normalize_text(write.description, "description"),
        trigger_description=_normalize_text(write.trigger_description, "trigger_description"),
        workflow=_normalize_workflow(write.workflow),
        preferred_tools=_normalize_string_list(write.preferred_tools, "preferred_tools"),
        tags=_normalize_string_list(write.tags, "tags"),
        workflow_category=_normalize_optional_text(write.workflow_category),
        confidence=confidence,
        source_episode_ids=_normalize_string_list(write.source_episode_ids, "source_episode_ids", require_non_empty=True),
        status=status,  # type: ignore[arg-type]
        dedup_group_id=_normalize_optional_text(write.dedup_group_id),
        source_job_id=_normalize_optional_text(write.source_job_id),
        id=_normalize_optional_text(write.id),
    )


class ProceduralSkillCandidateStore:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path

    def add_candidate(self, write: SkillCandidateWrite) -> SkillCandidateRecord:
        normalized = validate_skill_candidate_write(write)
        if normalized.source_job_id:
            existing = self.get_by_source_job_id(normalized.source_job_id)
            if existing is not None:
                return existing
        candidate_id = normalized.id or make_skill_candidate_id(normalized)
        existing = self.get_by_id(candidate_id)
        if existing is not None:
            return existing
        dedup_group_id = normalized.dedup_group_id or candidate_id
        conn = get_connection(self.db_path)
        try:
            conn.execute(
                """
                INSERT INTO skill_candidates (
                    id, title, description, trigger_description, workflow_json,
                    preferred_tools_json, tags_json, workflow_category, confidence,
                    occurrences, source_episode_ids_json, status, dedup_group_id,
                    source_job_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                """,
                (
                    candidate_id,
                    normalized.title,
                    normalized.description,
                    normalized.trigger_description,
                    canonical_json(list(normalized.workflow)),
                    canonical_json(list(normalized.preferred_tools)),
                    canonical_json(list(normalized.tags)),
                    normalized.workflow_category,
                    normalized.confidence,
                    1,
                    canonical_json(list(normalized.source_episode_ids)),
                    normalized.status,
                    dedup_group_id,
                    normalized.source_job_id,
                ),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        record = self.get_by_id(candidate_id)
        if record is None:
            raise RuntimeError("Inserted skill candidate could not be read back")
        return record

    def get_by_id(self, candidate_id: str) -> Optional[SkillCandidateRecord]:
        conn = get_connection(self.db_path)
        try:
            row = conn.execute("SELECT * FROM skill_candidates WHERE id = ?", (candidate_id,)).fetchone()
            return self._row_to_record(row) if row is not None else None
        finally:
            conn.close()

    def get_by_source_job_id(self, source_job_id: str) -> Optional[SkillCandidateRecord]:
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                """
                SELECT * FROM skill_candidates
                WHERE source_job_id = ?
                ORDER BY created_at ASC, id ASC
                LIMIT 1
                """,
                (source_job_id,),
            ).fetchone()
            return self._row_to_record(row) if row is not None else None
        finally:
            conn.close()

    def list_by_status(self, status: SkillCandidateStatus, limit: int = 100) -> List[SkillCandidateRecord]:
        if status not in VALID_SKILL_CANDIDATE_STATUSES:
            raise SkillCandidateValidationError("status", "must be valid")
        conn = get_connection(self.db_path)
        try:
            rows = conn.execute(
                """
                SELECT * FROM skill_candidates
                WHERE status = ?
                ORDER BY confidence DESC, occurrences DESC, created_at ASC, id ASC
                LIMIT ?
                """,
                (status, int(limit)),
            ).fetchall()
            return [self._row_to_record(row) for row in rows]
        finally:
            conn.close()

    def list_ready_for_promotion(self, limit: int = 100) -> List[SkillCandidateRecord]:
        return self.list_by_status("READY_FOR_PROMOTION", limit=limit)

    def transition_ready_to_waiting(self, candidate_id: str) -> SkillCandidateRecord:
        return self._transition_status(
            candidate_id,
            expected_status="READY_FOR_PROMOTION",
            next_status="WAITING_FOR_APPROVAL",
        )

    def transition_waiting_to_promoted(self, candidate_id: str) -> SkillCandidateRecord:
        return self._transition_status(
            candidate_id,
            expected_status="WAITING_FOR_APPROVAL",
            next_status="PROMOTED",
        )

    def transition_waiting_to_rejected(self, candidate_id: str) -> SkillCandidateRecord:
        return self._transition_status(
            candidate_id,
            expected_status="WAITING_FOR_APPROVAL",
            next_status="REJECTED",
        )
    def list_recent(self, limit: int = 100) -> List[SkillCandidateRecord]:
        conn = get_connection(self.db_path)
        try:
            rows = conn.execute(
                """
                SELECT * FROM skill_candidates
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
            return [self._row_to_record(row) for row in rows]
        finally:
            conn.close()

    def list_by_dedup_group(self, dedup_group_id: str) -> List[SkillCandidateRecord]:
        conn = get_connection(self.db_path)
        try:
            rows = conn.execute(
                """
                SELECT * FROM skill_candidates
                WHERE dedup_group_id = ?
                ORDER BY created_at ASC, id ASC
                """,
                (dedup_group_id,),
            ).fetchall()
            return [self._row_to_record(row) for row in rows]
        finally:
            conn.close()

    def list_for_episode(self, episode_id: str) -> List[SkillCandidateRecord]:
        return [
            record
            for record in self.list_recent(limit=1000)
            if str(episode_id) in {str(source_id) for source_id in record.source_episode_ids}
        ]

    def apply_new(self, write: SkillCandidateWrite, dedup_group_id: str) -> SkillCandidateRecord:
        return self.add_candidate(
            SkillCandidateWrite(
                **{
                    **validate_skill_candidate_write(write).__dict__,
                    "dedup_group_id": dedup_group_id,
                    "status": _status_for(1, float(write.confidence)),
                }
            )
        )

    def apply_duplicate(self, target: SkillCandidateRecord, incoming: SkillCandidateWrite) -> SkillCandidateRecord:
        normalized = validate_skill_candidate_write(incoming)
        occurrence_increment = 1
        merged_episodes = _merge_unique(target.source_episode_ids, normalized.source_episode_ids)
        confidence = _updated_confidence(target.confidence, normalized.confidence, occurrence_increment)
        status = _status_for(target.occurrences + occurrence_increment, confidence, target.status)
        return self._update_candidate(
            target.id,
            title=target.title,
            description=target.description,
            trigger_description=target.trigger_description,
            workflow=target.workflow,
            preferred_tools=target.preferred_tools,
            tags=target.tags,
            workflow_category=target.workflow_category,
            confidence=confidence,
            occurrences=target.occurrences + occurrence_increment,
            source_episode_ids=merged_episodes,
            status=status,
            dedup_group_id=target.dedup_group_id or target.id,
            source_job_id=target.source_job_id,
        )

    def apply_update(self, target: SkillCandidateRecord, incoming: SkillCandidateWrite) -> SkillCandidateRecord:
        normalized = validate_skill_candidate_write(incoming)
        workflow = _merge_workflow(target.workflow, list(normalized.workflow))
        tools = _merge_unique(target.preferred_tools, normalized.preferred_tools)
        tags = _merge_unique(target.tags, normalized.tags)
        episodes = _merge_unique(target.source_episode_ids, normalized.source_episode_ids)
        confidence = _updated_confidence(target.confidence, normalized.confidence, 1)
        occurrences = target.occurrences + 1
        status = _status_for(occurrences, confidence, target.status)
        return self._update_candidate(
            target.id,
            title=normalized.title or target.title,
            description=normalized.description or target.description,
            trigger_description=normalized.trigger_description or target.trigger_description,
            workflow=workflow,
            preferred_tools=tools,
            tags=tags,
            workflow_category=normalized.workflow_category or target.workflow_category,
            confidence=confidence,
            occurrences=occurrences,
            source_episode_ids=episodes,
            status=status,
            dedup_group_id=target.dedup_group_id or target.id,
            source_job_id=target.source_job_id,
        )

    def apply_merge(self, targets: Sequence[SkillCandidateRecord], incoming: SkillCandidateWrite) -> SkillCandidateRecord:
        if not targets:
            return self.apply_new(incoming, make_skill_candidate_id(incoming))
        normalized = validate_skill_candidate_write(incoming)
        canonical = sorted(targets, key=lambda record: (-record.occurrences, -record.confidence, record.created_at, record.id))[0]
        group_id = canonical.dedup_group_id or canonical.id
        workflow = list(normalized.workflow)
        tools = list(normalized.preferred_tools)
        tags = list(normalized.tags)
        episodes = list(normalized.source_episode_ids)
        additional_episode_count = 1
        for target in targets:
            workflow = _merge_workflow(workflow, target.workflow)
            tools = _merge_unique(tools, target.preferred_tools)
            tags = _merge_unique(tags, target.tags)
            before = set(episodes)
            episodes = _merge_unique(episodes, target.source_episode_ids)
            additional_episode_count += len(set(episodes) - before)
            if target.id != canonical.id and target.status not in TERMINAL_OR_APPROVAL_STATUSES:
                self._update_group_and_status(target.id, group_id, _status_for(target.occurrences, target.confidence, target.status))
        occurrences = max(canonical.occurrences + 1, additional_episode_count)
        confidence = _updated_confidence(canonical.confidence, normalized.confidence, max(1, additional_episode_count))
        status = _status_for(occurrences, confidence, canonical.status)
        return self._update_candidate(
            canonical.id,
            title=normalized.title or canonical.title,
            description=normalized.description or canonical.description,
            trigger_description=normalized.trigger_description or canonical.trigger_description,
            workflow=workflow,
            preferred_tools=tools,
            tags=tags,
            workflow_category=normalized.workflow_category or canonical.workflow_category,
            confidence=confidence,
            occurrences=occurrences,
            source_episode_ids=episodes,
            status=status,
            dedup_group_id=group_id,
            source_job_id=canonical.source_job_id,
        )

    def update_status(self, candidate_id: str, status: SkillCandidateStatus) -> SkillCandidateRecord:
        existing = self.get_by_id(candidate_id)
        if existing is None:
            raise SkillCandidateValidationError("id", "candidate does not exist")
        return self._update_candidate(
            existing.id,
            title=existing.title,
            description=existing.description,
            trigger_description=existing.trigger_description,
            workflow=existing.workflow,
            preferred_tools=existing.preferred_tools,
            tags=existing.tags,
            workflow_category=existing.workflow_category,
            confidence=existing.confidence,
            occurrences=existing.occurrences,
            source_episode_ids=existing.source_episode_ids,
            status=status,
            dedup_group_id=existing.dedup_group_id,
            source_job_id=existing.source_job_id,
        )

    def _update_group_and_status(self, candidate_id: str, dedup_group_id: str, status: SkillCandidateStatus) -> None:
        conn = get_connection(self.db_path)
        try:
            conn.execute(
                """
                UPDATE skill_candidates
                SET dedup_group_id = ?, status = ?, updated_at = datetime('now')
                WHERE id = ?
                """,
                (dedup_group_id, status, candidate_id),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _update_candidate(
        self,
        candidate_id: str,
        *,
        title: str,
        description: str,
        trigger_description: str,
        workflow: Sequence[Mapping[str, Any]],
        preferred_tools: Sequence[str],
        tags: Sequence[str],
        workflow_category: Optional[str],
        confidence: float,
        occurrences: int,
        source_episode_ids: Sequence[str],
        status: SkillCandidateStatus,
        dedup_group_id: Optional[str],
        source_job_id: Optional[str],
    ) -> SkillCandidateRecord:
        if status not in VALID_SKILL_CANDIDATE_STATUSES:
            raise SkillCandidateValidationError("status", "must be valid")
        conn = get_connection(self.db_path)
        try:
            conn.execute(
                """
                UPDATE skill_candidates
                SET title = ?, description = ?, trigger_description = ?, workflow_json = ?,
                    preferred_tools_json = ?, tags_json = ?, workflow_category = ?, confidence = ?,
                    occurrences = ?, source_episode_ids_json = ?, status = ?, dedup_group_id = ?,
                    source_job_id = ?, updated_at = datetime('now')
                WHERE id = ?
                """,
                (
                    _normalize_text(title, "title"),
                    _normalize_text(description, "description"),
                    _normalize_text(trigger_description, "trigger_description"),
                    canonical_json(_normalize_workflow(workflow)),
                    canonical_json(_normalize_string_list(preferred_tools, "preferred_tools")),
                    canonical_json(_normalize_string_list(tags, "tags")),
                    _normalize_optional_text(workflow_category),
                    float(confidence),
                    int(occurrences),
                    canonical_json(_normalize_string_list(source_episode_ids, "source_episode_ids", require_non_empty=True)),
                    status,
                    dedup_group_id,
                    source_job_id,
                    candidate_id,
                ),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        record = self.get_by_id(candidate_id)
        if record is None:
            raise RuntimeError("Updated skill candidate could not be read back")
        return record

    def _transition_status(
        self,
        candidate_id: str,
        *,
        expected_status: SkillCandidateStatus,
        next_status: SkillCandidateStatus,
    ) -> SkillCandidateRecord:
        existing = self.get_by_id(candidate_id)
        if existing is None:
            raise SkillCandidateValidationError("id", "candidate does not exist")
        if existing.status == next_status:
            return existing
        if existing.status != expected_status:
            raise SkillCandidateValidationError(
                "status",
                f"cannot transition {existing.status} to {next_status}; expected {expected_status}",
            )
        return self.update_status(candidate_id, next_status)
    @staticmethod
    def _row_to_record(row: Any) -> SkillCandidateRecord:
        return SkillCandidateRecord(
            id=str(row["id"]),
            title=str(row["title"]),
            description=str(row["description"]),
            trigger_description=str(row["trigger_description"]),
            workflow=[dict(item) for item in parse_json_list(row["workflow_json"]) if isinstance(item, Mapping)],
            preferred_tools=[str(item) for item in parse_json_list(row["preferred_tools_json"])],
            tags=[str(item) for item in parse_json_list(row["tags_json"])],
            workflow_category=row["workflow_category"],
            confidence=float(row["confidence"]),
            occurrences=int(row["occurrences"]),
            source_episode_ids=[str(item) for item in parse_json_list(row["source_episode_ids_json"])],
            status=str(row["status"]),  # type: ignore[arg-type]
            dedup_group_id=row["dedup_group_id"],
            source_job_id=row["source_job_id"],
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )


def _updated_confidence(existing: float, incoming: float, additional_occurrences: int) -> float:
    return min(0.99, max(float(existing), float(incoming)) + min(0.05, 0.01 * int(additional_occurrences)))


def _merge_workflow(*workflows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    merged: List[Dict[str, Any]] = []
    for workflow in workflows:
        for step in workflow:
            instruction = _normalize_text(step.get("instruction"), "workflow")
            key = instruction.lower()
            if key in seen:
                continue
            seen.add(key)
            merged.append({"order": len(merged) + 1, "instruction": instruction, "tool_hint": _normalize_optional_text(step.get("tool_hint"))})
    return merged

