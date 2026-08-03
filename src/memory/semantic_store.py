from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from src.db import get_connection, query_facts_fts


class SemanticFactValidationError(ValueError):
    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message
        super().__init__(f"{field}: {message}")


@dataclass(frozen=True)
class SemanticFactWrite:
    category: str
    fact_text: str
    source: str = "user"
    confidence: float = 1.0
    explicit: bool = True


@dataclass(frozen=True)
class SemanticFactRecord:
    id: int
    category: str
    fact_text: str
    source: str
    confidence: float
    created_at: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "category": self.category,
            "fact_text": self.fact_text,
            "source": self.source,
            "confidence": self.confidence,
            "created_at": self.created_at,
        }


def _normalize_whitespace(value: str) -> str:
    return " ".join(str(value).split())


def _require_non_empty(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise SemanticFactValidationError(field, "must be a string")
    normalized = _normalize_whitespace(value)
    if not normalized:
        raise SemanticFactValidationError(field, "must be non-empty")
    return normalized


def validate_semantic_fact_write(fact: SemanticFactWrite) -> SemanticFactWrite:
    try:
        confidence = float(fact.confidence)
    except (TypeError, ValueError) as exc:
        raise SemanticFactValidationError("confidence", "must be a number") from exc
    if confidence < 0 or confidence > 1:
        raise SemanticFactValidationError("confidence", "must be between 0 and 1")
    if not bool(fact.explicit):
        raise SemanticFactValidationError("explicit", "must be true for permanent writes")

    return SemanticFactWrite(
        category=_require_non_empty(fact.category, "category"),
        fact_text=_require_non_empty(fact.fact_text, "fact_text"),
        source=_require_non_empty(fact.source, "source"),
        confidence=confidence,
        explicit=True,
    )


class SemanticFactStore:
    def __init__(self, db_path: Optional[Path] = None, memory_path: Optional[Path] = None):
        self.db_path = db_path
        self.memory_path = memory_path

    def add_explicit_fact(
        self,
        fact: SemanticFactWrite,
        *,
        dedup_service: Any = None,
        candidate_id: Optional[str] = None,
        source_job_id: Optional[str] = None,
        llm_route_payload: Optional[Mapping[str, Any]] = None,
    ) -> SemanticFactRecord:
        """Store an explicit permanent fact after mandatory Phase 7B dedup."""
        validated = validate_semantic_fact_write(fact)
        from src.memory.embeddings import (
            SEMANTIC_FACT_OWNER_TYPE,
            EmbeddingInput,
            canonical_semantic_fact_text,
        )
        from src.memory.semantic_dedup import (
            SemanticDedupInput,
            SemanticDedupDecision,
            SemanticDedupService,
        )

        service = dedup_service or SemanticDedupService(db_path=self.db_path)
        dedup_input = SemanticDedupInput(
            fact=validated,
            candidate_id=candidate_id,
            source_job_id=source_job_id,
            llm_route_payload=llm_route_payload,
        )
        decision = service.decide(dedup_input)

        if decision.action == "NEW":
            record = self._insert_fact(
                category=decision.category,
                fact_text=decision.new_fact_text,
                source=validated.source,
                confidence=decision.confidence,
            )
            self._upsert_fact_embedding(record, service)
        elif decision.action == "DUPLICATE":
            if not decision.target_fact_id:
                raise SemanticFactValidationError("target_fact_id", "DUPLICATE requires target fact id")
            record = self.get_by_id(int(decision.target_fact_id))
            if record is None:
                raise SemanticFactValidationError("target_fact_id", "target fact does not exist")
            if not service.embedding_store.list_embeddings_for_owner(SEMANTIC_FACT_OWNER_TYPE, str(record.id)):
                self._upsert_fact_embedding(record, service)
        elif decision.action == "UPDATE":
            if not decision.target_fact_id:
                raise SemanticFactValidationError("target_fact_id", "UPDATE requires target fact id")
            existing = self.get_by_id(int(decision.target_fact_id))
            if existing is None:
                raise SemanticFactValidationError("target_fact_id", "target fact does not exist")
            record = self._update_fact(
                fact_id=existing.id,
                category=decision.category,
                fact_text=decision.new_fact_text,
                source=existing.source or validated.source,
                confidence=max(float(existing.confidence), float(decision.confidence), float(validated.confidence)),
            )
            self._upsert_fact_embedding(record, service)
        elif decision.action == "MERGE":
            if not decision.target_fact_id:
                raise SemanticFactValidationError("target_fact_id", "MERGE requires target fact id")
            existing = self.get_by_id(int(decision.target_fact_id))
            if existing is None:
                raise SemanticFactValidationError("target_fact_id", "target fact does not exist")
            merged_records = [self.get_by_id(int(fact_id)) for fact_id in decision.merged_fact_ids]
            merged_records = [record for record in merged_records if record is not None]
            max_confidence = max(
                [float(existing.confidence), float(decision.confidence), float(validated.confidence)]
                + [float(record.confidence) for record in merged_records]
            )
            record = self._update_fact(
                fact_id=existing.id,
                category=decision.category,
                fact_text=decision.new_fact_text,
                source=existing.source or validated.source,
                confidence=max_confidence,
            )
            for fact_id in decision.merged_fact_ids:
                if str(fact_id) != str(record.id):
                    self._delete_fact(int(fact_id))
                    service.embedding_store.delete_embeddings_for_owner(SEMANTIC_FACT_OWNER_TYPE, str(fact_id))
            self._upsert_fact_embedding(record, service)
        else:
            raise SemanticFactValidationError("action", "unknown dedup action")

        service.record_event(dedup_input, decision, getattr(service, "last_context", {}))
        self.sync_memory_md()
        return record

    def get_by_id(self, fact_id: int) -> Optional[SemanticFactRecord]:
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                """
                SELECT rowid AS id, category, fact_text, source, confidence, created_at
                FROM facts
                WHERE rowid = ?
                """,
                (int(fact_id),),
            ).fetchone()
            return self._row_to_record(row) if row is not None else None
        finally:
            conn.close()

    def list_facts(self) -> List[SemanticFactRecord]:
        conn = get_connection(self.db_path)
        try:
            rows = conn.execute(
                """
                SELECT rowid AS id, category, fact_text, source, confidence, created_at
                FROM facts
                ORDER BY rowid DESC
                """
            ).fetchall()
            return [self._row_to_record(row) for row in rows]
        finally:
            conn.close()

    def search_facts(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        return query_facts_fts(query=query, limit=limit, db_path=self.db_path)

    def sync_memory_md(self) -> str:
        from src.config import MEMORY_PATH

        conn = get_connection(self.db_path)
        try:
            rows = conn.execute(
                "SELECT category, fact_text, created_at FROM facts ORDER BY category, rowid DESC"
            ).fetchall()
        finally:
            conn.close()

        target_memory = self.memory_path or MEMORY_PATH
        target_memory.parent.mkdir(parents=True, exist_ok=True)

        if not rows:
            content = "# Semantic Memory (MEMORY.md Mirror)\n\n*No facts recorded yet.*\n"
            target_memory.write_text(content, encoding="utf-8")
            return content

        categories: Dict[str, List[str]] = {}
        for row in rows:
            category = row["category"] or "General"
            categories.setdefault(category, []).append(str(row["fact_text"]))

        lines = [
            "# Semantic Memory (MEMORY.md Mirror)\n",
            "*Auto-synced from SQLite `facts` table.*\n",
        ]
        for category, facts in categories.items():
            lines.append(f"## {category.capitalize()}")
            for fact_text in facts:
                lines.append(f"- {fact_text}")
            lines.append("")

        content = "\n".join(lines)
        target_memory.write_text(content, encoding="utf-8")
        return content

    def _insert_fact(self, *, category: str, fact_text: str, source: str, confidence: float) -> SemanticFactRecord:
        conn = get_connection(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO facts (category, fact_text, source, confidence, created_at)
                VALUES (?, ?, ?, ?, datetime('now'))
                """,
                (category, fact_text, source, str(confidence)),
            )
            rowid = int(cursor.lastrowid)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        record = self.get_by_id(rowid)
        if record is None:
            raise RuntimeError("Inserted semantic fact could not be read back")
        return record

    def _update_fact(
        self,
        *,
        fact_id: int,
        category: str,
        fact_text: str,
        source: str,
        confidence: float,
    ) -> SemanticFactRecord:
        conn = get_connection(self.db_path)
        try:
            conn.execute(
                """
                UPDATE facts
                SET category = ?, fact_text = ?, source = ?, confidence = ?
                WHERE rowid = ?
                """,
                (category, fact_text, source, str(confidence), int(fact_id)),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        record = self.get_by_id(fact_id)
        if record is None:
            raise RuntimeError("Updated semantic fact could not be read back")
        return record

    def _delete_fact(self, fact_id: int) -> None:
        conn = get_connection(self.db_path)
        try:
            conn.execute("DELETE FROM facts WHERE rowid = ?", (int(fact_id),))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _upsert_fact_embedding(record: SemanticFactRecord, service: Any) -> None:
        from src.memory.embeddings import SEMANTIC_FACT_OWNER_TYPE, EmbeddingInput, canonical_semantic_fact_text

        service.embedding_store.upsert_embedding(
            EmbeddingInput(
                owner_type=SEMANTIC_FACT_OWNER_TYPE,
                owner_id=str(record.id),
                text=canonical_semantic_fact_text(record.category, record.fact_text, record.source),
                metadata={"fact_id": str(record.id), "phase": "7B"},
            ),
            provider=getattr(service, "embedding_provider", None),
        )

    @staticmethod
    def _row_to_record(row: Any) -> SemanticFactRecord:
        return SemanticFactRecord(
            id=int(row["id"]),
            category=str(row["category"]),
            fact_text=str(row["fact_text"]),
            source=str(row["source"]),
            confidence=float(row["confidence"]),
            created_at=str(row["created_at"]),
        )
