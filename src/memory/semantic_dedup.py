import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Mapping, Optional, Protocol, Sequence, Tuple

from src.db import get_connection
from src.memory.embeddings import (
    DEFAULT_EMBEDDING_MODEL,
    EmbeddingProvider,
    SemanticEmbeddingStore,
    SimilarFactMatch,
    canonical_metadata_json,
    canonical_semantic_fact_text,
    content_hash,
    normalize_fact_tokens,
    normalize_embedding_text,
)
from src.memory.semantic_store import SemanticFactWrite


DedupAction = Literal["NEW", "DUPLICATE", "UPDATE", "MERGE"]
VALID_DEDUP_ACTIONS = {"NEW", "DUPLICATE", "UPDATE", "MERGE"}
DUPLICATE_THRESHOLD = 0.96
UPDATE_THRESHOLD = 0.88
DEFAULT_SIMILAR_FACT_TOP_K = 5


class SemanticDedupValidationError(ValueError):
    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message
        super().__init__(f"{field}: {message}")


@dataclass(frozen=True)
class SemanticDedupInput:
    fact: SemanticFactWrite
    candidate_id: Optional[str] = None
    source_job_id: Optional[str] = None
    llm_route_payload: Optional[Mapping[str, Any]] = None


@dataclass(frozen=True)
class SimilarSemanticFact:
    fact_id: str
    category: str
    fact_text: str
    source: str
    confidence: float
    similarity: float
    strategy: str


@dataclass(frozen=True)
class SemanticDedupDecision:
    action: DedupAction
    new_fact_text: str
    category: str
    confidence: float
    target_fact_id: Optional[str] = None
    merged_fact_ids: List[str] = field(default_factory=list)
    similar_fact_ids: List[str] = field(default_factory=list)
    reason: str = ""
    classifier_provider: Optional[str] = None
    classifier_model: Optional[str] = None
    classifier_used: bool = False
    fallback_used: bool = False


@dataclass(frozen=True)
class SemanticDedupEventRecord:
    id: str
    candidate_id: Optional[str]
    new_fact_text: str
    action: DedupAction
    target_fact_id: Optional[str]
    merged_fact_ids: List[str]
    similar_fact_ids: List[str]
    llm_provider: Optional[str]
    llm_model: Optional[str]
    reason: Optional[str]
    confidence: Optional[float]
    context: Dict[str, Any]
    source_job_id: Optional[str]
    created_at: str


class SemanticDedupClassifier(Protocol):
    def classify(
        self,
        input: SemanticDedupInput,
        similar_facts: Sequence[SimilarSemanticFact],
    ) -> SemanticDedupDecision:
        ...


def _normalize_optional_string(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    normalized = " ".join(str(value).split())
    return normalized or None


def _canonical_json_array(values: Sequence[str]) -> str:
    return json.dumps([str(value) for value in values], sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _parse_json_array(value: Optional[str]) -> List[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]


def _specificity_score(text: str) -> int:
    return len(set(normalize_fact_tokens(text)))


def _tokens_contain(left: str, right: str) -> bool:
    left_tokens = set(normalize_fact_tokens(left))
    right_tokens = set(normalize_fact_tokens(right))
    return bool(left_tokens and right_tokens and right_tokens < left_tokens)


def _is_contradictory(left: str, right: str) -> bool:
    left_norm = normalize_embedding_text(left)
    right_norm = normalize_embedding_text(right)
    contradiction_pairs = [
        (" dark ", " light "),
        (" enabled ", " disabled "),
        (" true ", " false "),
        (" yes ", " no "),
        (" python ", " java "),
    ]
    padded_left = f" {left_norm} "
    padded_right = f" {right_norm} "
    for a, b in contradiction_pairs:
        if (a in padded_left and b in padded_right) or (b in padded_left and a in padded_right):
            return True
    return False


def _merge_fact_text(incoming: str, matches: Sequence[SimilarSemanticFact]) -> str:
    parts: List[str] = []
    seen = set()
    for text in [match.fact_text for match in matches] + [incoming]:
        clean = " ".join(str(text).split()).strip()
        key = clean.lower()
        if clean and key not in seen:
            seen.add(key)
            parts.append(clean.rstrip("."))
    return "; ".join(parts)


class DeterministicSemanticDedupClassifier:
    def classify(
        self,
        input: SemanticDedupInput,
        similar_facts: Sequence[SimilarSemanticFact],
    ) -> SemanticDedupDecision:
        incoming = " ".join(input.fact.fact_text.split())
        category = " ".join(input.fact.category.split())
        confidence = float(input.fact.confidence)
        similar_ids = [fact.fact_id for fact in similar_facts]
        if not similar_facts:
            return SemanticDedupDecision(
                action="NEW",
                new_fact_text=incoming,
                category=category,
                confidence=confidence,
                similar_fact_ids=[],
                reason="No existing permanent facts",
                fallback_used=True,
            )

        top = similar_facts[0]
        exact_same = normalize_embedding_text(top.fact_text) == normalize_embedding_text(incoming)
        if exact_same or top.similarity >= DUPLICATE_THRESHOLD:
            return SemanticDedupDecision(
                action="DUPLICATE",
                new_fact_text=top.fact_text,
                category=top.category,
                confidence=max(confidence, top.confidence),
                target_fact_id=top.fact_id,
                similar_fact_ids=similar_ids,
                reason="Incoming fact duplicates an existing permanent fact",
                fallback_used=True,
            )

        merge_matches = [
            match
            for match in similar_facts
            if match.similarity >= UPDATE_THRESHOLD
            and match.category == category
            and not _is_contradictory(incoming, match.fact_text)
        ]
        if len(merge_matches) >= 2:
            target = merge_matches[0]
            merged_ids = [match.fact_id for match in merge_matches[1:]]
            return SemanticDedupDecision(
                action="MERGE",
                new_fact_text=_merge_fact_text(incoming, merge_matches),
                category=category,
                confidence=max([confidence] + [match.confidence for match in merge_matches]),
                target_fact_id=target.fact_id,
                merged_fact_ids=merged_ids,
                similar_fact_ids=similar_ids,
                reason="Multiple compatible facts can be conservatively merged",
                fallback_used=True,
            )

        if (
            top.similarity >= UPDATE_THRESHOLD
            and top.category == category
            and _tokens_contain(incoming, top.fact_text)
            and not _is_contradictory(incoming, top.fact_text)
            and _specificity_score(incoming) > _specificity_score(top.fact_text)
        ):
            return SemanticDedupDecision(
                action="UPDATE",
                new_fact_text=incoming,
                category=category,
                confidence=max(confidence, top.confidence),
                target_fact_id=top.fact_id,
                similar_fact_ids=similar_ids,
                reason="Incoming fact is a more specific version of one existing fact",
                fallback_used=True,
            )

        return SemanticDedupDecision(
            action="NEW",
            new_fact_text=incoming,
            category=category,
            confidence=confidence,
            similar_fact_ids=similar_ids,
            reason="No safe duplicate, update, or merge decision",
            fallback_used=True,
        )


class SemanticDedupService:
    def __init__(
        self,
        db_path: Optional[Path] = None,
        embedding_store: Optional[SemanticEmbeddingStore] = None,
        embedding_provider: Optional[EmbeddingProvider] = None,
        classifier: Optional[SemanticDedupClassifier] = None,
    ):
        self.db_path = db_path
        self.embedding_store = embedding_store or SemanticEmbeddingStore(db_path=db_path)
        self.embedding_provider = embedding_provider
        self.classifier = classifier or DeterministicSemanticDedupClassifier()
        self.last_context: Dict[str, Any] = {}

    def decide(self, input: SemanticDedupInput) -> SemanticDedupDecision:
        from src.memory.semantic_store import SemanticFactStore

        existing_facts = SemanticFactStore(db_path=self.db_path).list_facts()
        query_text = canonical_semantic_fact_text(input.fact.category, input.fact.fact_text)
        matches = self.embedding_store.top_k_similar_facts(
            text=query_text,
            facts=existing_facts,
            k=DEFAULT_SIMILAR_FACT_TOP_K,
            provider=self.embedding_provider,
        )
        similar = [self._match_to_similar_fact(match) for match in matches]
        self.last_context = self._build_context(input=input, matches=matches)
        decision = self.classifier.classify(input, similar)
        return validate_dedup_decision(decision, known_fact_ids={str(fact.id) for fact in existing_facts})

    def record_event(
        self,
        input: SemanticDedupInput,
        decision: SemanticDedupDecision,
        context: Optional[Dict[str, Any]] = None,
    ) -> SemanticDedupEventRecord:
        valid = validate_dedup_decision(decision)
        context_json = dict(context if context is not None else self.last_context)
        event_id = make_dedup_event_id(input, valid, context_json)
        conn = get_connection(self.db_path)
        try:
            conn.execute(
                """
                INSERT INTO semantic_dedup_events (
                    id, candidate_id, new_fact_text, action, target_fact_id,
                    merged_fact_ids_json, similar_fact_ids_json, llm_provider,
                    llm_model, reason, confidence, context_json, source_job_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (
                    event_id,
                    input.candidate_id,
                    valid.new_fact_text,
                    valid.action,
                    valid.target_fact_id,
                    _canonical_json_array(valid.merged_fact_ids),
                    _canonical_json_array(valid.similar_fact_ids),
                    valid.classifier_provider,
                    valid.classifier_model,
                    valid.reason,
                    valid.confidence,
                    canonical_metadata_json(context_json),
                    input.source_job_id,
                ),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        record = self.get_event(event_id)
        if record is None:
            raise RuntimeError("Inserted semantic dedup event could not be read back")
        return record

    def decide_and_record(self, input: SemanticDedupInput) -> Tuple[SemanticDedupDecision, SemanticDedupEventRecord]:
        decision = self.decide(input)
        event = self.record_event(input, decision, self.last_context)
        return decision, event

    def get_event(self, event_id: str) -> Optional[SemanticDedupEventRecord]:
        conn = get_connection(self.db_path)
        try:
            row = conn.execute("SELECT * FROM semantic_dedup_events WHERE id = ?", (event_id,)).fetchone()
            return self._row_to_event(row) if row is not None else None
        finally:
            conn.close()

    def list_events(self, limit: int = 100) -> List[SemanticDedupEventRecord]:
        conn = get_connection(self.db_path)
        try:
            rows = conn.execute(
                "SELECT * FROM semantic_dedup_events ORDER BY created_at DESC, id DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
            return [self._row_to_event(row) for row in rows]
        finally:
            conn.close()

    @staticmethod
    def _match_to_similar_fact(match: SimilarFactMatch) -> SimilarSemanticFact:
        fact = match.fact
        return SimilarSemanticFact(
            fact_id=str(fact.id),
            category=str(fact.category),
            fact_text=str(fact.fact_text),
            source=str(fact.source),
            confidence=float(fact.confidence),
            similarity=float(match.similarity),
            strategy=match.strategy,
        )

    @staticmethod
    def _build_context(input: SemanticDedupInput, matches: Sequence[SimilarFactMatch]) -> Dict[str, Any]:
        return {
            "phase": "7B",
            "thresholds": {"duplicate": DUPLICATE_THRESHOLD, "update": UPDATE_THRESHOLD},
            "similar_facts": [
                {
                    "fact_id": str(match.fact.id),
                    "similarity": float(match.similarity),
                    "strategy": match.strategy,
                }
                for match in matches
            ],
            "embedding_model": (
                matches[0].embedding.embedding_model
                if matches and matches[0].embedding is not None
                else DEFAULT_EMBEDDING_MODEL
            ),
            "embedding_fallback_used": True,
            "classifier_used": False,
            "classifier_fallback_used": True,
            "incoming_content_hash": content_hash(input.fact.fact_text),
        }

    @staticmethod
    def _row_to_event(row: Any) -> SemanticDedupEventRecord:
        return SemanticDedupEventRecord(
            id=str(row["id"]),
            candidate_id=row["candidate_id"],
            new_fact_text=str(row["new_fact_text"]),
            action=str(row["action"]),  # type: ignore[arg-type]
            target_fact_id=row["target_fact_id"],
            merged_fact_ids=_parse_json_array(row["merged_fact_ids_json"]),
            similar_fact_ids=_parse_json_array(row["similar_fact_ids_json"]),
            llm_provider=row["llm_provider"],
            llm_model=row["llm_model"],
            reason=row["reason"],
            confidence=float(row["confidence"]) if row["confidence"] is not None else None,
            context=json.loads(row["context_json"]) if row["context_json"] else {},
            source_job_id=row["source_job_id"],
            created_at=str(row["created_at"]),
        )


def validate_dedup_decision(
    decision: SemanticDedupDecision,
    known_fact_ids: Optional[set[str]] = None,
) -> SemanticDedupDecision:
    action = str(decision.action or "")
    if action not in VALID_DEDUP_ACTIONS:
        raise SemanticDedupValidationError("action", "must be NEW, DUPLICATE, UPDATE, or MERGE")
    fact_text = " ".join(str(decision.new_fact_text or "").split())
    category = " ".join(str(decision.category or "").split())
    if not fact_text:
        raise SemanticDedupValidationError("new_fact_text", "must be non-empty")
    if not category:
        raise SemanticDedupValidationError("category", "must be non-empty")
    try:
        confidence = float(decision.confidence)
    except (TypeError, ValueError) as exc:
        raise SemanticDedupValidationError("confidence", "must be a number") from exc
    if confidence < 0 or confidence > 1:
        raise SemanticDedupValidationError("confidence", "must be between 0 and 1")

    target_fact_id = _normalize_optional_string(decision.target_fact_id)
    merged_fact_ids = [_normalize_optional_string(item) for item in decision.merged_fact_ids]
    merged_fact_ids = [item for item in merged_fact_ids if item]
    similar_fact_ids = [_normalize_optional_string(item) for item in decision.similar_fact_ids]
    similar_fact_ids = [item for item in similar_fact_ids if item]
    if action in {"DUPLICATE", "UPDATE", "MERGE"} and not target_fact_id:
        raise SemanticDedupValidationError("target_fact_id", f"{action} requires a target fact id")
    if action == "MERGE" and not merged_fact_ids:
        raise SemanticDedupValidationError("merged_fact_ids", "MERGE requires at least one merged fact id")
    if target_fact_id and known_fact_ids is not None and target_fact_id not in known_fact_ids:
        raise SemanticDedupValidationError("target_fact_id", "target fact id is unknown")
    if known_fact_ids is not None:
        for fact_id in merged_fact_ids:
            if fact_id not in known_fact_ids:
                raise SemanticDedupValidationError("merged_fact_ids", "merged fact id is unknown")
    if target_fact_id in merged_fact_ids:
        merged_fact_ids = [fact_id for fact_id in merged_fact_ids if fact_id != target_fact_id]
    return SemanticDedupDecision(
        action=action,  # type: ignore[arg-type]
        new_fact_text=fact_text,
        category=category,
        confidence=confidence,
        target_fact_id=target_fact_id,
        merged_fact_ids=merged_fact_ids,
        similar_fact_ids=similar_fact_ids,
        reason=str(decision.reason or ""),
        classifier_provider=decision.classifier_provider,
        classifier_model=decision.classifier_model,
        classifier_used=bool(decision.classifier_used),
        fallback_used=bool(decision.fallback_used),
    )


def make_dedup_event_id(
    input: SemanticDedupInput,
    decision: SemanticDedupDecision,
    context: Mapping[str, Any],
) -> str:
    return f"dedup_event_{uuid.uuid4().hex}"


