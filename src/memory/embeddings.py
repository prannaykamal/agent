import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Protocol, Sequence

from src.db import get_connection


SEMANTIC_FACT_OWNER_TYPE = "semantic_fact"
DEFAULT_EMBEDDING_MODEL = "deterministic-fallback-v1"
DEFAULT_EMBEDDING_DIMENSIONS = 64


class EmbeddingValidationError(ValueError):
    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message
        super().__init__(f"{field}: {message}")


@dataclass(frozen=True)
class EmbeddingInput:
    owner_type: str
    owner_id: str
    text: str
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EmbeddingVector:
    model: str
    dimensions: int
    values: List[float]
    provider: str
    fallback_used: bool


@dataclass(frozen=True)
class SemanticEmbeddingRecord:
    id: str
    owner_type: str
    owner_id: str
    embedding_model: str
    embedding_dim: int
    embedding: List[float]
    content_hash: str
    metadata: Dict[str, Any]
    created_at: str
    updated_at: str


class EmbeddingProvider(Protocol):
    model: str
    dimensions: int

    def embed_text(self, text: str) -> EmbeddingVector:
        ...


@dataclass(frozen=True)
class SimilarFactMatch:
    fact: Any
    embedding: Optional[SemanticEmbeddingRecord]
    similarity: float
    strategy: Literal["embedding", "lexical_fallback"]


@dataclass(frozen=True)
class EmbeddingProviderConfig:
    provider: str = "deterministic"
    model: str = DEFAULT_EMBEDDING_MODEL
    dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS
    allow_fallback: bool = True


def normalize_embedding_text(text: str) -> str:
    return " ".join(str(text or "").lower().split())


def normalize_fact_tokens(text: str) -> List[str]:
    normalized = normalize_embedding_text(text)
    words = re.findall(r"[a-z0-9]+", normalized)
    stop_words = {
        "a",
        "an",
        "and",
        "are",
        "as",
        "for",
        "in",
        "is",
        "of",
        "on",
        "or",
        "that",
        "the",
        "to",
        "user",
        "users",
        "with",
    }
    tokens: List[str] = []
    for word in words:
        if word in stop_words or len(word) <= 1:
            continue
        if len(word) > 4 and word.endswith("s"):
            word = word[:-1]
        tokens.append(word)
    return tokens


def content_hash(text: str) -> str:
    return hashlib.sha256(normalize_embedding_text(text).encode("utf-8")).hexdigest()


def canonical_embedding_json(values: Sequence[float]) -> str:
    parsed = [float(value) for value in values]
    if not parsed:
        raise EmbeddingValidationError("embedding", "must be non-empty")
    return json.dumps(parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def parse_embedding_json(value: str) -> List[float]:
    try:
        parsed = json.loads(value)
    except Exception as exc:
        raise EmbeddingValidationError("embedding_json", "must be valid JSON") from exc
    if not isinstance(parsed, list) or not parsed:
        raise EmbeddingValidationError("embedding_json", "must be a non-empty array")
    result: List[float] = []
    for index, item in enumerate(parsed):
        if not isinstance(item, (int, float)):
            raise EmbeddingValidationError("embedding_json", f"item {index} must be numeric")
        result.append(float(item))
    return result


def canonical_metadata_json(value: Dict[str, Any]) -> str:
    return json.dumps(value or {}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def parse_metadata_json(value: Optional[str]) -> Dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(float(a) * float(b) for a, b in zip(left, right))
    left_norm = math.sqrt(sum(float(a) * float(a) for a in left))
    right_norm = math.sqrt(sum(float(b) * float(b) for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def lexical_similarity(left: str, right: str) -> float:
    left_tokens = set(normalize_fact_tokens(left))
    right_tokens = set(normalize_fact_tokens(right))
    if not left_tokens or not right_tokens:
        return 0.0
    intersection = len(left_tokens & right_tokens)
    union = len(left_tokens | right_tokens)
    containment = intersection / max(1, min(len(left_tokens), len(right_tokens)))
    jaccard = intersection / max(1, union)
    return (0.80 * containment) + (0.20 * jaccard)


class DeterministicFallbackEmbeddingProvider:
    def __init__(
        self,
        model: str = DEFAULT_EMBEDDING_MODEL,
        dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS,
    ):
        if int(dimensions) <= 0:
            raise EmbeddingValidationError("dimensions", "must be positive")
        self.model = model or DEFAULT_EMBEDDING_MODEL
        self.dimensions = int(dimensions)

    def embed_text(self, text: str) -> EmbeddingVector:
        normalized = normalize_embedding_text(text)
        if not normalized:
            raise EmbeddingValidationError("text", "must be non-empty")
        values = [0.0 for _ in range(self.dimensions)]
        for token in normalize_fact_tokens(normalized) or [normalized]:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            values[index] += sign
        norm = math.sqrt(sum(value * value for value in values))
        if norm:
            values = [value / norm for value in values]
        return EmbeddingVector(
            model=self.model,
            dimensions=self.dimensions,
            values=values,
            provider="deterministic",
            fallback_used=True,
        )


def get_embedding_provider(config: Optional[EmbeddingProviderConfig] = None) -> EmbeddingProvider:
    resolved = config or EmbeddingProviderConfig()
    provider = str(resolved.provider or "deterministic").lower()
    if provider == "deterministic" or resolved.allow_fallback:
        return DeterministicFallbackEmbeddingProvider(
            model=resolved.model or DEFAULT_EMBEDDING_MODEL,
            dimensions=resolved.dimensions or DEFAULT_EMBEDDING_DIMENSIONS,
        )
    raise EmbeddingValidationError("provider", f"unsupported embedding provider: {resolved.provider}")


def make_embedding_id(owner_type: str, owner_id: str, embedding_model: str) -> str:
    digest = hashlib.sha256(f"{owner_type}|{owner_id}|{embedding_model}".encode("utf-8")).hexdigest()[:24]
    return f"embedding_{digest}"


def canonical_semantic_fact_text(category: str, fact_text: str, source: Optional[str] = None) -> str:
    lines = [f"Category: {category}", f"Fact: {fact_text}"]
    if source is not None:
        lines.append(f"Source: {source}")
    return "\n".join(lines)


def _validate_embedding_input(input: EmbeddingInput) -> EmbeddingInput:
    owner_type = str(input.owner_type or "").strip()
    owner_id = str(input.owner_id or "").strip()
    text = str(input.text or "").strip()
    model = str(input.embedding_model or DEFAULT_EMBEDDING_MODEL).strip()
    if owner_type != SEMANTIC_FACT_OWNER_TYPE:
        raise EmbeddingValidationError("owner_type", "Phase 7B supports semantic_fact embeddings only")
    if not owner_id:
        raise EmbeddingValidationError("owner_id", "must be non-empty")
    if not text:
        raise EmbeddingValidationError("text", "must be non-empty")
    if not model:
        raise EmbeddingValidationError("embedding_model", "must be non-empty")
    if not isinstance(input.metadata, dict):
        raise EmbeddingValidationError("metadata", "must be a dictionary")
    return EmbeddingInput(
        owner_type=owner_type,
        owner_id=owner_id,
        text=text,
        embedding_model=model,
        metadata=dict(input.metadata),
    )


class SemanticEmbeddingStore:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path

    def upsert_embedding(
        self,
        input: EmbeddingInput,
        provider: Optional[EmbeddingProvider] = None,
    ) -> SemanticEmbeddingRecord:
        normalized = _validate_embedding_input(input)
        active_provider = provider or get_embedding_provider(
            EmbeddingProviderConfig(model=normalized.embedding_model)
        )
        vector = active_provider.embed_text(normalized.text)
        embedding_id = make_embedding_id(normalized.owner_type, normalized.owner_id, vector.model)
        metadata = dict(normalized.metadata)
        metadata.update(
            {
                "provider": vector.provider,
                "fallback_used": vector.fallback_used,
                "source": "phase_7b_semantic_embeddings",
            }
        )
        text_hash = content_hash(normalized.text)

        conn = get_connection(self.db_path)
        try:
            conn.execute(
                """
                INSERT INTO semantic_embeddings (
                    id, owner_type, owner_id, embedding_model, embedding_dim,
                    embedding_json, content_hash, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                ON CONFLICT(owner_type, owner_id, embedding_model) DO UPDATE SET
                    embedding_dim = excluded.embedding_dim,
                    embedding_json = excluded.embedding_json,
                    content_hash = excluded.content_hash,
                    metadata_json = excluded.metadata_json,
                    updated_at = datetime('now')
                """,
                (
                    embedding_id,
                    normalized.owner_type,
                    normalized.owner_id,
                    vector.model,
                    vector.dimensions,
                    canonical_embedding_json(vector.values),
                    text_hash,
                    canonical_metadata_json(metadata),
                ),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        record = self.get_embedding(normalized.owner_type, normalized.owner_id, vector.model)
        if record is None:
            raise RuntimeError("Upserted semantic embedding could not be read back")
        return record

    def get_embedding(
        self,
        owner_type: str,
        owner_id: str,
        embedding_model: str,
    ) -> Optional[SemanticEmbeddingRecord]:
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                """
                SELECT * FROM semantic_embeddings
                WHERE owner_type = ? AND owner_id = ? AND embedding_model = ?
                """,
                (owner_type, str(owner_id), embedding_model),
            ).fetchone()
            return self._row_to_record(row) if row is not None else None
        finally:
            conn.close()

    def list_embeddings_for_owner(self, owner_type: str, owner_id: str) -> List[SemanticEmbeddingRecord]:
        conn = get_connection(self.db_path)
        try:
            rows = conn.execute(
                """
                SELECT * FROM semantic_embeddings
                WHERE owner_type = ? AND owner_id = ?
                ORDER BY embedding_model
                """,
                (owner_type, str(owner_id)),
            ).fetchall()
            return [self._row_to_record(row) for row in rows]
        finally:
            conn.close()

    def delete_embeddings_for_owner(self, owner_type: str, owner_id: str) -> int:
        conn = get_connection(self.db_path)
        try:
            cursor = conn.execute(
                "DELETE FROM semantic_embeddings WHERE owner_type = ? AND owner_id = ?",
                (owner_type, str(owner_id)),
            )
            conn.commit()
            return int(cursor.rowcount or 0)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def top_k_similar_facts(
        self,
        text: str,
        facts: Sequence[Any],
        k: int = 5,
        provider: Optional[EmbeddingProvider] = None,
    ) -> List[SimilarFactMatch]:
        query_text = str(text or "").strip()
        if not query_text or not facts:
            return []
        active_provider = provider or get_embedding_provider()
        query_vector = active_provider.embed_text(query_text)
        matches: List[SimilarFactMatch] = []
        for fact in facts:
            fact_text = canonical_semantic_fact_text(
                category=str(getattr(fact, "category", "")),
                fact_text=str(getattr(fact, "fact_text", "")),
            )
            embedding = self.get_embedding(SEMANTIC_FACT_OWNER_TYPE, str(getattr(fact, "id")), query_vector.model)
            if embedding is None:
                embedding = self.upsert_embedding(
                    EmbeddingInput(
                        owner_type=SEMANTIC_FACT_OWNER_TYPE,
                        owner_id=str(getattr(fact, "id")),
                        text=canonical_semantic_fact_text(
                            category=str(getattr(fact, "category", "")),
                            fact_text=str(getattr(fact, "fact_text", "")),
                            source=str(getattr(fact, "source", "")),
                        ),
                        embedding_model=query_vector.model,
                        metadata={"generated_for": "dedup_similarity"},
                    ),
                    provider=active_provider,
                )
            embedding_score = cosine_similarity(query_vector.values, embedding.embedding)
            lexical_score = lexical_similarity(query_text, fact_text)
            if lexical_score > embedding_score:
                matches.append(SimilarFactMatch(fact=fact, embedding=embedding, similarity=lexical_score, strategy="lexical_fallback"))
            else:
                matches.append(SimilarFactMatch(fact=fact, embedding=embedding, similarity=embedding_score, strategy="embedding"))
        matches.sort(key=lambda item: item.similarity, reverse=True)
        return matches[: max(0, int(k))]

    @staticmethod
    def _row_to_record(row: Any) -> SemanticEmbeddingRecord:
        return SemanticEmbeddingRecord(
            id=str(row["id"]),
            owner_type=str(row["owner_type"]),
            owner_id=str(row["owner_id"]),
            embedding_model=str(row["embedding_model"]),
            embedding_dim=int(row["embedding_dim"]),
            embedding=parse_embedding_json(str(row["embedding_json"])),
            content_hash=str(row["content_hash"]),
            metadata=parse_metadata_json(row["metadata_json"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

