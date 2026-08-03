import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Sequence

from src.db import get_connection
from src.memory.semantic_store import SemanticFactWrite


CandidateStatus = Literal[
    "PENDING",
    "IN_CONSOLIDATION",
    "PROMOTED",
    "DISCARDED",
    "DEFERRED",
    "FAILED",
]

VALID_CANDIDATE_STATUSES = {
    "PENDING",
    "IN_CONSOLIDATION",
    "PROMOTED",
    "DISCARDED",
    "DEFERRED",
    "FAILED",
}


class PendingFactCandidateValidationError(ValueError):
    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message
        super().__init__(f"{field}: {message}")


@dataclass(frozen=True)
class PendingFactCandidateWrite:
    session_id: str
    fact: str
    category: str
    confidence: float
    explicit: bool
    source: str
    source_message_id: Optional[str] = None
    source_episode_id: Optional[str] = None
    batch_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    id: Optional[str] = None
    status: CandidateStatus = "PENDING"


@dataclass(frozen=True)
class PendingFactCandidateRecord:
    id: str
    session_id: str
    source_message_id: Optional[str]
    source_episode_id: Optional[str]
    fact: str
    category: str
    confidence: float
    explicit: bool
    source: str
    status: CandidateStatus
    batch_id: Optional[str]
    metadata: Dict[str, Any]
    created_at: str
    updated_at: str
    processed_at: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "source_message_id": self.source_message_id,
            "source_episode_id": self.source_episode_id,
            "fact": self.fact,
            "fact_text": self.fact,
            "category": self.category,
            "confidence": self.confidence,
            "explicit": self.explicit,
            "source": self.source,
            "status": self.status,
            "batch_id": self.batch_id,
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "processed_at": self.processed_at,
        }


def canonical_metadata_json(value: Dict[str, Any]) -> str:
    return json.dumps(value or {}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _parse_metadata_json(value: Optional[str]) -> Dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _normalize_whitespace(value: str) -> str:
    return " ".join(str(value).split())


def _require_non_empty(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise PendingFactCandidateValidationError(field, "must be a string")
    normalized = _normalize_whitespace(value)
    if not normalized:
        raise PendingFactCandidateValidationError(field, "must be non-empty")
    return normalized


def _normalize_optional_string(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    normalized = _normalize_whitespace(str(value))
    return normalized or None


def _short_hash(value: str, length: int = 24) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def make_pending_fact_candidate_id(candidate: PendingFactCandidateWrite) -> str:
    normalized = validate_pending_fact_candidate_write(candidate, require_id=False)
    canonical_input = "|".join(
        [
            normalized.session_id,
            normalized.source,
            normalized.source_message_id or "",
            normalized.source_episode_id or "",
            normalized.fact.lower(),
            normalized.category.lower(),
        ]
    )
    return f"fact_candidate_{_short_hash(canonical_input)}"


def validate_pending_fact_candidate_write(
    candidate: PendingFactCandidateWrite,
    *,
    require_id: bool = False,
) -> PendingFactCandidateWrite:
    try:
        confidence = float(candidate.confidence)
    except (TypeError, ValueError) as exc:
        raise PendingFactCandidateValidationError("confidence", "must be a number") from exc
    if confidence < 0 or confidence > 1:
        raise PendingFactCandidateValidationError("confidence", "must be between 0 and 1")
    status = _require_non_empty(candidate.status, "status")
    if status not in VALID_CANDIDATE_STATUSES:
        raise PendingFactCandidateValidationError("status", "must be a valid candidate status")
    candidate_id = _normalize_optional_string(candidate.id)
    if require_id and not candidate_id:
        raise PendingFactCandidateValidationError("id", "must be non-empty")
    if not isinstance(candidate.metadata, dict):
        raise PendingFactCandidateValidationError("metadata", "must be a dictionary")

    return PendingFactCandidateWrite(
        id=candidate_id,
        session_id=_require_non_empty(candidate.session_id, "session_id"),
        fact=_require_non_empty(candidate.fact, "fact"),
        category=_require_non_empty(candidate.category, "category"),
        confidence=confidence,
        explicit=bool(candidate.explicit),
        source=_require_non_empty(candidate.source, "source"),
        source_message_id=_normalize_optional_string(candidate.source_message_id),
        source_episode_id=_normalize_optional_string(candidate.source_episode_id),
        batch_id=_normalize_optional_string(candidate.batch_id),
        metadata=dict(candidate.metadata),
        status=status,  # type: ignore[arg-type]
    )


class PendingFactCandidateStore:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path

    def add_candidate(self, candidate: PendingFactCandidateWrite) -> PendingFactCandidateRecord:
        normalized = validate_pending_fact_candidate_write(candidate)
        candidate_id = normalized.id or make_pending_fact_candidate_id(normalized)
        existing = self.get_by_id(candidate_id)
        if existing is not None:
            return existing

        conn = get_connection(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO pending_fact_candidates (
                    id,
                    session_id,
                    source_message_id,
                    source_episode_id,
                    fact,
                    category,
                    confidence,
                    explicit,
                    source,
                    status,
                    batch_id,
                    metadata_json,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                """,
                (
                    candidate_id,
                    normalized.session_id,
                    normalized.source_message_id,
                    normalized.source_episode_id,
                    normalized.fact,
                    normalized.category,
                    normalized.confidence,
                    1 if normalized.explicit else 0,
                    normalized.source,
                    normalized.status,
                    normalized.batch_id,
                    canonical_metadata_json(normalized.metadata),
                ),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            conn.rollback()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        record = self.get_by_id(candidate_id)
        if record is None:
            raise RuntimeError("Inserted pending fact candidate could not be read back")
        return record

    def add_candidates(self, candidates: Sequence[PendingFactCandidateWrite]) -> List[PendingFactCandidateRecord]:
        return [self.add_candidate(candidate) for candidate in candidates]

    def get_by_id(self, candidate_id: str) -> Optional[PendingFactCandidateRecord]:
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                """
                SELECT * FROM pending_fact_candidates
                WHERE id = ?
                """,
                (candidate_id,),
            ).fetchone()
            return self._row_to_record(row) if row is not None else None
        finally:
            conn.close()

    def list_by_session(
        self,
        session_id: str,
        status: Optional[CandidateStatus] = None,
        limit: int = 100,
    ) -> List[PendingFactCandidateRecord]:
        conn = get_connection(self.db_path)
        try:
            if status is None:
                rows = conn.execute(
                    """
                    SELECT * FROM pending_fact_candidates
                    WHERE session_id = ?
                    ORDER BY created_at DESC, id DESC
                    LIMIT ?
                    """,
                    (session_id, int(limit)),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM pending_fact_candidates
                    WHERE session_id = ? AND status = ?
                    ORDER BY created_at DESC, id DESC
                    LIMIT ?
                    """,
                    (session_id, status, int(limit)),
                ).fetchall()
            return [self._row_to_record(row) for row in rows]
        finally:
            conn.close()

    def list_pending(self, limit: int = 100) -> List[PendingFactCandidateRecord]:
        conn = get_connection(self.db_path)
        try:
            rows = conn.execute(
                """
                SELECT * FROM pending_fact_candidates
                WHERE status = 'PENDING'
                ORDER BY created_at ASC, id ASC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
            return [self._row_to_record(row) for row in rows]
        finally:
            conn.close()

    def claim_pending_batch(
        self,
        *,
        session_id: str,
        batch_id: str,
        limit: int = 100,
        candidate_ids: Optional[Sequence[str]] = None,
        metadata_update: Optional[Dict[str, Any]] = None,
    ) -> List[PendingFactCandidateRecord]:
        normalized_session_id = _require_non_empty(session_id, "session_id")
        normalized_batch_id = _require_non_empty(batch_id, "batch_id")
        capped_limit = max(1, int(limit))
        conn = get_connection(self.db_path)
        try:
            if candidate_ids:
                wanted = [str(candidate_id) for candidate_id in candidate_ids if str(candidate_id).strip()]
                if not wanted:
                    return []
                placeholders = ",".join("?" for _ in wanted)
                rows = conn.execute(
                    f"""
                    SELECT * FROM pending_fact_candidates
                    WHERE session_id = ? AND status = 'PENDING' AND id IN ({placeholders})
                    ORDER BY created_at ASC, id ASC
                    LIMIT ?
                    """,
                    (normalized_session_id, *wanted, capped_limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM pending_fact_candidates
                    WHERE session_id = ? AND status = 'PENDING'
                    ORDER BY created_at ASC, id ASC
                    LIMIT ?
                    """,
                    (normalized_session_id, capped_limit),
                ).fetchall()

            claimed_ids = [str(row["id"]) for row in rows]
            for row in rows:
                metadata = _parse_metadata_json(row["metadata_json"])
                metadata.update(dict(metadata_update or {}))
                conn.execute(
                    """
                    UPDATE pending_fact_candidates
                    SET status = 'IN_CONSOLIDATION',
                        batch_id = ?,
                        metadata_json = ?,
                        updated_at = datetime('now')
                    WHERE id = ? AND status = 'PENDING'
                    """,
                    (normalized_batch_id, canonical_metadata_json(metadata), str(row["id"])),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return [record for candidate_id in claimed_ids if (record := self.get_by_id(candidate_id)) is not None]

    def update_status(
        self,
        candidate_id: str,
        status: CandidateStatus,
        *,
        metadata_update: Optional[Dict[str, Any]] = None,
        batch_id: Optional[str] = None,
        processed: bool = False,
    ) -> Optional[PendingFactCandidateRecord]:
        if status not in VALID_CANDIDATE_STATUSES:
            raise PendingFactCandidateValidationError("status", "must be a valid candidate status")
        existing = self.get_by_id(candidate_id)
        if existing is None:
            return None
        metadata = dict(existing.metadata)
        metadata.update(dict(metadata_update or {}))
        effective_batch_id = batch_id if batch_id is not None else existing.batch_id
        conn = get_connection(self.db_path)
        try:
            if processed:
                conn.execute(
                    """
                    UPDATE pending_fact_candidates
                    SET status = ?,
                        batch_id = ?,
                        metadata_json = ?,
                        processed_at = datetime('now'),
                        updated_at = datetime('now')
                    WHERE id = ?
                    """,
                    (status, effective_batch_id, canonical_metadata_json(metadata), candidate_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE pending_fact_candidates
                    SET status = ?,
                        batch_id = ?,
                        metadata_json = ?,
                        updated_at = datetime('now')
                    WHERE id = ?
                    """,
                    (status, effective_batch_id, canonical_metadata_json(metadata), candidate_id),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return self.get_by_id(candidate_id)

    def update_status_many(
        self,
        candidate_ids: Sequence[str],
        status: CandidateStatus,
        *,
        metadata_update: Optional[Dict[str, Any]] = None,
        batch_id: Optional[str] = None,
        processed: bool = False,
    ) -> List[PendingFactCandidateRecord]:
        records: List[PendingFactCandidateRecord] = []
        for candidate_id in candidate_ids:
            record = self.update_status(
                str(candidate_id),
                status,
                metadata_update=metadata_update,
                batch_id=batch_id,
                processed=processed,
            )
            if record is not None:
                records.append(record)
        return records

    def recover_stale_in_consolidation(
        self,
        *,
        session_id: Optional[str] = None,
        batch_id: Optional[str] = None,
        metadata_update: Optional[Dict[str, Any]] = None,
    ) -> int:
        clauses = ["status = 'IN_CONSOLIDATION'"]
        params: List[Any] = []
        if session_id is not None:
            clauses.append("session_id = ?")
            params.append(_require_non_empty(session_id, "session_id"))
        if batch_id is not None:
            clauses.append("batch_id = ?")
            params.append(_require_non_empty(batch_id, "batch_id"))

        conn = get_connection(self.db_path)
        try:
            rows = conn.execute(
                f"SELECT * FROM pending_fact_candidates WHERE {' AND '.join(clauses)}",
                tuple(params),
            ).fetchall()
            for row in rows:
                metadata = _parse_metadata_json(row["metadata_json"])
                metadata.update(dict(metadata_update or {}))
                metadata.setdefault("recovered_from_status", "IN_CONSOLIDATION")
                conn.execute(
                    """
                    UPDATE pending_fact_candidates
                    SET status = 'PENDING',
                        metadata_json = ?,
                        updated_at = datetime('now')
                    WHERE id = ?
                    """,
                    (canonical_metadata_json(metadata), str(row["id"])),
                )
            conn.commit()
            return len(rows)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    def count_by_session(self, session_id: str, status: Optional[CandidateStatus] = None) -> int:
        conn = get_connection(self.db_path)
        try:
            if status is None:
                row = conn.execute(
                    "SELECT COUNT(*) FROM pending_fact_candidates WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) FROM pending_fact_candidates WHERE session_id = ? AND status = ?",
                    (session_id, status),
                ).fetchone()
            return int(row[0] or 0)
        finally:
            conn.close()

    @staticmethod
    def _row_to_record(row: Any) -> PendingFactCandidateRecord:
        return PendingFactCandidateRecord(
            id=str(row["id"]),
            session_id=str(row["session_id"]),
            source_message_id=row["source_message_id"],
            source_episode_id=row["source_episode_id"],
            fact=str(row["fact"]),
            category=str(row["category"]),
            confidence=float(row["confidence"]),
            explicit=bool(row["explicit"]),
            source=str(row["source"]),
            status=str(row["status"]),  # type: ignore[arg-type]
            batch_id=row["batch_id"],
            metadata=_parse_metadata_json(row["metadata_json"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            processed_at=row["processed_at"],
        )


def _clean_extracted_fact(value: str) -> str:
    cleaned = _normalize_whitespace(value)
    cleaned = cleaned.strip(" .!?,;:")
    return cleaned


def extract_explicit_facts_from_user_text(user_text: str) -> List[SemanticFactWrite]:
    text = str(user_text or "")
    if not text.strip():
        return []

    patterns = [
        (r"\bremember that\s+(.+?)(?:[.!?](?:\s|$)|$)", "user_fact", 0.98, "Remember that {fact}"),
        (r"\bplease remember(?: that)?\s+(.+?)(?:[.!?](?:\s|$)|$)", "user_fact", 0.98, "Remember that {fact}"),
        (r"\bdo not forget(?: that)?\s+(.+?)(?:[.!?](?:\s|$)|$)", "user_fact", 0.98, "Do not forget that {fact}"),
        (r"\bdon't forget(?: that)?\s+(.+?)(?:[.!?](?:\s|$)|$)", "user_fact", 0.98, "Do not forget that {fact}"),
        (
            r"\bmy name is\s+([A-Za-z][A-Za-z0-9 .'\-]{0,80}?)(?:\s+and\b|[.!?;,](?:\s|$)|$)",
            "user_profile",
            0.99,
            "User's name is {fact}",
        ),
        (
            r"\bmy email is\s+([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})",
            "user_contact",
            0.99,
            "User's email is {fact}",
        ),
    ]

    facts: List[SemanticFactWrite] = []
    seen = set()
    for pattern, category, confidence, template in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE | re.DOTALL):
            extracted = _clean_extracted_fact(match.group(1))
            if not extracted:
                continue
            fact_text = template.format(fact=extracted)
            key = (category, fact_text.lower())
            if key in seen:
                continue
            seen.add(key)
            facts.append(
                SemanticFactWrite(
                    category=category,
                    fact_text=fact_text,
                    source="deterministic_explicit_chat",
                    confidence=confidence,
                    explicit=True,
                )
            )
    return facts



