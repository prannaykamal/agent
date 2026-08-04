import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Literal, Mapping, Optional, Sequence

from src.db import get_connection
from src.hitl.approval_engine import create_approval_request
from src.memory.procedural_candidates import (
    ProceduralSkillCandidateStore,
    SkillCandidateRecord,
    SkillCandidateValidationError,
)
from src.memory.skill_store import SkillVersionStore, SkillVersionWrite

ApprovalAction = Literal["PROMOTE_SKILL", "MODIFY_SKILL", "REJECT_SKILL"]
ApprovalStatus = Literal["PENDING", "APPROVED", "REJECTED", "MODIFIED", "CANCELLED"]


@dataclass(frozen=True)
class ProceduralSkillApprovalRecord:
    id: str
    approval_request_id: str
    candidate_id: Optional[str]
    skill_version_id: Optional[str]
    action: ApprovalAction
    status: ApprovalStatus
    modified_payload: Optional[Dict[str, Any]]
    created_at: str
    decided_at: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "approval_request_id": self.approval_request_id,
            "candidate_id": self.candidate_id,
            "skill_version_id": self.skill_version_id,
            "action": self.action,
            "status": self.status,
            "modified_payload": self.modified_payload,
            "created_at": self.created_at,
            "decided_at": self.decided_at,
        }


@dataclass(frozen=True)
class ProceduralSkillApprovalDecisionResult:
    handled: bool
    approval_request_id: str
    candidate_id: Optional[str]
    decision: str
    status: str
    skill_version_id: Optional[str] = None
    reloaded: bool = False
    message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "handled": self.handled,
            "approval_request_id": self.approval_request_id,
            "candidate_id": self.candidate_id,
            "decision": self.decision,
            "status": self.status,
            "skill_version_id": self.skill_version_id,
            "reloaded": self.reloaded,
            "message": self.message,
        }


@dataclass(frozen=True)
class ProceduralSkillApprovalRequestResult:
    approval: ProceduralSkillApprovalRecord
    approval_request: Dict[str, Any]
    candidate: SkillCandidateRecord
    reused: bool = False


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _parse_json_object(value: Any) -> Optional[Dict[str, Any]]:
    if value is None or value == "":
        return None
    try:
        parsed = json.loads(str(value))
    except Exception:
        return None
    return dict(parsed) if isinstance(parsed, Mapping) else None


def _short_hash(value: str, length: int = 18) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def _approval_id(approval_request_id: str) -> str:
    return f"procapproval_{_short_hash(str(approval_request_id), 18)}"


def _normalize_words(text: str, limit: int = 8) -> List[str]:
    stop_words = {
        "about",
        "after",
        "again",
        "and",
        "for",
        "from",
        "into",
        "that",
        "the",
        "this",
        "when",
        "with",
        "workflow",
        "skill",
        "use",
        "using",
    }
    words: List[str] = []
    for raw in re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]+", str(text or "").lower()):
        word = raw.strip("-_")
        if len(word) < 3 or word in stop_words or word in words:
            continue
        words.append(word)
        if len(words) >= limit:
            break
    return words


def _render_execution_steps(candidate: SkillCandidateRecord) -> str:
    lines: List[str] = []
    steps = sorted(candidate.workflow, key=lambda item: (int(item.get("order", 9999)), str(item.get("instruction", ""))))
    for index, step in enumerate(steps, start=1):
        instruction = re.sub(r"\s+", " ", str(step.get("instruction") or "")).strip()
        if not instruction:
            continue
        tool_hint = re.sub(r"\s+", " ", str(step.get("tool_hint") or "")).strip()
        suffix = f" (tool: {tool_hint})" if tool_hint else ""
        lines.append(f"{index}. {instruction}{suffix}")
    if not lines:
        raise SkillCandidateValidationError("workflow", "must contain at least one instruction")
    return "\n".join(lines)


def _trigger_keywords(candidate: SkillCandidateRecord) -> List[str]:
    values: List[str] = []
    for value in list(candidate.tags) + _normalize_words(candidate.trigger_description) + _normalize_words(candidate.title, limit=4):
        normalized = re.sub(r"\s+", " ", str(value or "").strip().lower())
        if normalized and normalized not in values:
            values.append(normalized)
    return values or _normalize_words(candidate.title) or [candidate.id]


def _skill_version_write_from_candidate(candidate: SkillCandidateRecord, approval_request_id: str) -> SkillVersionWrite:
    tags = list(candidate.tags)
    if candidate.workflow_category and candidate.workflow_category not in tags:
        tags.append(candidate.workflow_category)
    return SkillVersionWrite(
        name=candidate.title,
        description=candidate.description,
        trigger_keywords=_trigger_keywords(candidate),
        execution_steps=_render_execution_steps(candidate),
        preferred_tools=candidate.preferred_tools,
        tags=tags,
        candidate_id=candidate.id,
        author="generated",
        approval_required=True,
        approval_id=approval_request_id,
        confidence=candidate.confidence,
        enabled=True,
        activate=True,
    )


def _candidate_preview_payload(candidate: SkillCandidateRecord) -> Dict[str, Any]:
    return {
        "candidate_id": candidate.id,
        "title": candidate.title,
        "description": candidate.description,
        "trigger_description": candidate.trigger_description,
        "workflow": list(candidate.workflow),
        "preferred_tools": list(candidate.preferred_tools),
        "tags": list(candidate.tags),
        "workflow_category": candidate.workflow_category,
        "confidence": candidate.confidence,
        "occurrences": candidate.occurrences,
        "source_episode_ids": list(candidate.source_episode_ids),
        "action": "PROMOTE_SKILL",
        "skill_version_preview": {
            "name": candidate.title,
            "trigger_keywords": _trigger_keywords(candidate),
            "execution_steps": _render_execution_steps(candidate),
            "preferred_tools": list(candidate.preferred_tools),
            "tags": list(candidate.tags) + ([candidate.workflow_category] if candidate.workflow_category else []),
        },
    }


def _get_skill_version_by_candidate(candidate_id: str, db_path: Optional[Path] = None):
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            """
            SELECT id FROM skill_versions
            WHERE candidate_id = ?
            ORDER BY created_at ASC, version ASC
            LIMIT 1
            """,
            (candidate_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return SkillVersionStore(db_path=db_path).get_version(str(row["id"]))


class ProceduralSkillApprovalRepository:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path

    def create_pending_for_candidate(
        self,
        *,
        approval_request_id: str,
        candidate_id: str,
        action: ApprovalAction = "PROMOTE_SKILL",
        proposed_payload: Optional[Mapping[str, Any]] = None,
    ) -> ProceduralSkillApprovalRecord:
        existing = self.get_by_approval_request_id(approval_request_id)
        if existing is not None:
            return existing
        open_existing = self.get_open_for_candidate(candidate_id)
        if open_existing is not None:
            return open_existing
        approval_id = _approval_id(approval_request_id)
        conn = get_connection(self.db_path)
        try:
            conn.execute(
                """
                INSERT INTO procedural_skill_approvals (
                    id, approval_request_id, candidate_id, skill_version_id, action,
                    status, modified_payload_json, created_at
                ) VALUES (?, ?, ?, NULL, ?, 'PENDING', ?, datetime('now'))
                """,
                (
                    approval_id,
                    str(approval_request_id),
                    str(candidate_id),
                    action,
                    _canonical_json(proposed_payload or {}),
                ),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        record = self.get_by_approval_request_id(approval_request_id)
        if record is None:
            raise RuntimeError("Inserted procedural skill approval could not be read back")
        return record

    def get_by_approval_request_id(self, approval_request_id: str) -> Optional[ProceduralSkillApprovalRecord]:
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT * FROM procedural_skill_approvals WHERE approval_request_id = ?",
                (str(approval_request_id),),
            ).fetchone()
            return self._row_to_record(row) if row is not None else None
        finally:
            conn.close()

    def get_open_for_candidate(self, candidate_id: str) -> Optional[ProceduralSkillApprovalRecord]:
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                """
                SELECT * FROM procedural_skill_approvals
                WHERE candidate_id = ? AND status IN ('PENDING', 'MODIFIED')
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (str(candidate_id),),
            ).fetchone()
            return self._row_to_record(row) if row is not None else None
        finally:
            conn.close()

    def has_open_or_successful_for_candidate(self, candidate_id: str) -> bool:
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                """
                SELECT 1 FROM procedural_skill_approvals
                WHERE candidate_id = ? AND status IN ('PENDING', 'APPROVED', 'MODIFIED')
                LIMIT 1
                """,
                (str(candidate_id),),
            ).fetchone()
            return row is not None
        finally:
            conn.close()

    def list_pending(self, limit: int = 100) -> List[ProceduralSkillApprovalRecord]:
        conn = get_connection(self.db_path)
        try:
            rows = conn.execute(
                """
                SELECT * FROM procedural_skill_approvals
                WHERE status = 'PENDING'
                ORDER BY created_at ASC, id ASC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
            return [self._row_to_record(row) for row in rows]
        finally:
            conn.close()

    def mark_approved(self, *, approval_request_id: str, skill_version_id: str) -> ProceduralSkillApprovalRecord:
        return self._mark(
            approval_request_id=approval_request_id,
            status="APPROVED",
            skill_version_id=skill_version_id,
        )

    def mark_rejected(self, approval_request_id: str) -> ProceduralSkillApprovalRecord:
        return self._mark(approval_request_id=approval_request_id, status="REJECTED")

    def mark_cancelled(self, approval_request_id: str) -> ProceduralSkillApprovalRecord:
        return self._mark(approval_request_id=approval_request_id, status="CANCELLED")

    def _mark(
        self,
        *,
        approval_request_id: str,
        status: ApprovalStatus,
        skill_version_id: Optional[str] = None,
    ) -> ProceduralSkillApprovalRecord:
        conn = get_connection(self.db_path)
        try:
            conn.execute(
                """
                UPDATE procedural_skill_approvals
                SET status = ?,
                    skill_version_id = COALESCE(?, skill_version_id),
                    decided_at = datetime('now')
                WHERE approval_request_id = ?
                """,
                (status, skill_version_id, str(approval_request_id)),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        record = self.get_by_approval_request_id(approval_request_id)
        if record is None:
            raise RuntimeError("Procedural skill approval could not be read after update")
        return record

    @staticmethod
    def _row_to_record(row: Any) -> ProceduralSkillApprovalRecord:
        action = str(row["action"])
        status = str(row["status"])
        return ProceduralSkillApprovalRecord(
            id=str(row["id"]),
            approval_request_id=str(row["approval_request_id"]),
            candidate_id=row["candidate_id"],
            skill_version_id=row["skill_version_id"],
            action=action,  # type: ignore[arg-type]
            status=status,  # type: ignore[arg-type]
            modified_payload=_parse_json_object(row["modified_payload_json"]),
            created_at=str(row["created_at"]),
            decided_at=row["decided_at"],
        )


def select_candidates_for_skill_promotion(
    *,
    candidate_store: ProceduralSkillCandidateStore,
    approval_repo: ProceduralSkillApprovalRepository,
    version_store: SkillVersionStore,
    candidate_ids: Optional[Sequence[str]] = None,
    max_candidates: int = 10,
) -> List[SkillCandidateRecord]:
    del version_store
    if candidate_ids:
        candidates = [candidate for candidate_id in candidate_ids if (candidate := candidate_store.get_by_id(str(candidate_id))) is not None]
        candidates = [candidate for candidate in candidates if candidate.status == "READY_FOR_PROMOTION"]
        candidates.sort(key=lambda item: (-item.confidence, -item.occurrences, item.created_at, item.id))
    else:
        candidates = candidate_store.list_ready_for_promotion(limit=max(1, int(max_candidates) * 2))

    selected: List[SkillCandidateRecord] = []
    for candidate in candidates:
        if len(selected) >= int(max_candidates):
            break
        if approval_repo.has_open_or_successful_for_candidate(candidate.id):
            continue
        if _get_skill_version_by_candidate(candidate.id, candidate_store.db_path) is not None:
            continue
        selected.append(candidate)
    return selected


def create_procedural_skill_approval_request(
    *,
    candidate: SkillCandidateRecord,
    session_id: str,
    candidate_store: Optional[ProceduralSkillCandidateStore] = None,
    approval_repo: Optional[ProceduralSkillApprovalRepository] = None,
    db_path: Optional[Path] = None,
) -> ProceduralSkillApprovalRequestResult:
    store = candidate_store or ProceduralSkillCandidateStore(db_path=db_path)
    repo = approval_repo or ProceduralSkillApprovalRepository(db_path=db_path)
    current = store.get_by_id(candidate.id)
    if current is None:
        raise SkillCandidateValidationError("id", "candidate does not exist")
    if current.status not in {"READY_FOR_PROMOTION", "WAITING_FOR_APPROVAL"}:
        raise SkillCandidateValidationError("status", "candidate is not eligible for promotion approval")

    existing_link = repo.get_open_for_candidate(current.id)
    if existing_link is not None:
        transitioned = current
        if current.status == "READY_FOR_PROMOTION":
            transitioned = store.transition_ready_to_waiting(current.id)
        return ProceduralSkillApprovalRequestResult(
            approval=existing_link,
            approval_request={"request_id": existing_link.approval_request_id},
            candidate=transitioned,
            reused=True,
        )

    if current.status != "READY_FOR_PROMOTION":
        raise SkillCandidateValidationError("status", "candidate is already waiting for approval without a linkage row")

    approval_payload = _candidate_preview_payload(current)
    request = create_approval_request(
        session_id=str(session_id or "procedural_memory"),
        tool_name="procedural_skill_promotion",
        tool_args=approval_payload,
        reason="Approve generated procedural skill before activation.",
        idempotency_key=f"procedural_skill_promotion:{current.id}:{current.updated_at}",
        db_path=db_path,
    )
    approval_request_id = str(request.get("request_id") or request.get("id") or "")
    if not approval_request_id:
        raise RuntimeError("HITL approval request did not return a request_id")
    link = repo.create_pending_for_candidate(
        approval_request_id=approval_request_id,
        candidate_id=current.id,
        action="PROMOTE_SKILL",
        proposed_payload=approval_payload,
    )
    transitioned = store.transition_ready_to_waiting(current.id)
    return ProceduralSkillApprovalRequestResult(
        approval=link,
        approval_request=request,
        candidate=transitioned,
        reused=False,
    )


def process_procedural_skill_approval_decision(
    *,
    approval_request_id: str,
    decision: Literal["APPROVED", "REJECTED"],
    db_path: Optional[Path] = None,
    skill_path: Optional[Path] = None,
    reload_registry: Any = None,
) -> ProceduralSkillApprovalDecisionResult:
    normalized_decision = str(decision).upper().strip()
    if normalized_decision not in {"APPROVED", "REJECTED"}:
        raise ValueError("decision must be APPROVED or REJECTED")

    approval_repo = ProceduralSkillApprovalRepository(db_path=db_path)
    approval = approval_repo.get_by_approval_request_id(approval_request_id)
    if approval is None:
        return ProceduralSkillApprovalDecisionResult(
            handled=False,
            approval_request_id=approval_request_id,
            candidate_id=None,
            decision=normalized_decision,
            status="NOT_PROCEDURAL",
            message="No procedural skill approval link found",
        )
    if approval.status in {"APPROVED", "REJECTED"}:
        return ProceduralSkillApprovalDecisionResult(
            handled=True,
            approval_request_id=approval_request_id,
            candidate_id=approval.candidate_id,
            decision=normalized_decision,
            status=approval.status,
            skill_version_id=approval.skill_version_id,
            reloaded=False,
            message="Procedural skill approval was already finalized",
        )
    if not approval.candidate_id:
        raise ValueError("procedural skill approval is missing candidate_id")

    candidate_store = ProceduralSkillCandidateStore(db_path=db_path)
    candidate = candidate_store.get_by_id(approval.candidate_id)
    if candidate is None:
        raise SkillCandidateValidationError("id", "linked candidate does not exist")

    if normalized_decision == "REJECTED":
        if candidate.status == "REJECTED":
            updated_link = approval_repo.mark_rejected(approval_request_id)
            return ProceduralSkillApprovalDecisionResult(True, approval_request_id, candidate.id, normalized_decision, updated_link.status, message="Candidate was already rejected")
        if candidate.status != "WAITING_FOR_APPROVAL":
            raise SkillCandidateValidationError("status", "rejection requires WAITING_FOR_APPROVAL candidate")
        updated_link = approval_repo.mark_rejected(approval_request_id)
        candidate_store.transition_waiting_to_rejected(candidate.id)
        return ProceduralSkillApprovalDecisionResult(
            handled=True,
            approval_request_id=approval_request_id,
            candidate_id=candidate.id,
            decision=normalized_decision,
            status=updated_link.status,
            message="Procedural skill promotion rejected",
        )

    existing_version = _get_skill_version_by_candidate(candidate.id, db_path)
    if existing_version is not None:
        updated_link = approval_repo.mark_approved(
            approval_request_id=approval_request_id,
            skill_version_id=existing_version.id,
        )
        if candidate.status == "WAITING_FOR_APPROVAL":
            candidate_store.transition_waiting_to_promoted(candidate.id)
        return ProceduralSkillApprovalDecisionResult(
            handled=True,
            approval_request_id=approval_request_id,
            candidate_id=candidate.id,
            decision=normalized_decision,
            status=updated_link.status,
            skill_version_id=existing_version.id,
            message="Existing promoted skill version reused",
        )

    if candidate.status != "WAITING_FOR_APPROVAL":
        raise SkillCandidateValidationError("status", "approval requires WAITING_FOR_APPROVAL candidate")

    version_store = SkillVersionStore(db_path=db_path, skill_path=skill_path)
    skill_version = version_store.create_version(_skill_version_write_from_candidate(candidate, approval_request_id))
    updated_link = approval_repo.mark_approved(
        approval_request_id=approval_request_id,
        skill_version_id=skill_version.id,
    )
    candidate_store.transition_waiting_to_promoted(candidate.id)

    reloaded = False
    try:
        if reload_registry is None:
            from src.memory.skill_reloader import SkillRuntimeReloader

            reload_registry = SkillRuntimeReloader(db_path=db_path, skill_path=skill_path)
        snapshot = reload_registry.reload_active_skills()
        reloaded = any(item.version_id == skill_version.id for item in snapshot.skills)
    except Exception:
        reloaded = False

    return ProceduralSkillApprovalDecisionResult(
        handled=True,
        approval_request_id=approval_request_id,
        candidate_id=candidate.id,
        decision=normalized_decision,
        status=updated_link.status,
        skill_version_id=skill_version.id,
        reloaded=reloaded,
        message="Procedural skill promoted after approval",
    )


def resume_approved_skill_promotions(
    *,
    limit: int = 50,
    db_path: Optional[Path] = None,
    skill_path: Optional[Path] = None,
    reload_registry: Any = None,
) -> List[ProceduralSkillApprovalDecisionResult]:
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT psa.approval_request_id
            FROM procedural_skill_approvals psa
            JOIN approval_requests ar ON ar.id = psa.approval_request_id
            WHERE psa.status = 'PENDING' AND ar.status = 'APPROVED'
            ORDER BY psa.created_at ASC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
    finally:
        conn.close()
    results: List[ProceduralSkillApprovalDecisionResult] = []
    for row in rows:
        results.append(
            process_procedural_skill_approval_decision(
                approval_request_id=str(row["approval_request_id"]),
                decision="APPROVED",
                db_path=db_path,
                skill_path=skill_path,
                reload_registry=reload_registry,
            )
        )
    return results