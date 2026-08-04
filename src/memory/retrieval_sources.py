from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Protocol, Sequence, Tuple

from src.db import get_connection
from src.memory.embeddings import (
    DEFAULT_EMBEDDING_MODEL,
    SEMANTIC_FACT_OWNER_TYPE,
    canonical_semantic_fact_text,
    cosine_similarity,
    get_embedding_provider,
    SemanticEmbeddingStore,
)
from src.memory.episode_store import StructuredEpisodeRecord, StructuredEpisodeRepository
from src.memory.retrieval_ranker import (
    clamp_score,
    estimate_retrieval_candidate_tokens,
    lexical_similarity,
    normalize_candidates,
    rank_candidates,
    recency_score,
    trim_retrieval_candidates_to_budget,
    weighted_score,
)
from src.memory.retrieval_types import (
    RetrievedMemoryCandidate,
    RetrievalBundle,
    RetrievalMemoryKind,
    RetrievalProvenance,
    RetrievalRequest,
    RetrievalScore,
    RetrievalSourceName,
    RetrievalSourceResult,
)
from src.memory.semantic_store import SemanticFactRecord, SemanticFactStore
from src.memory.skill_reloader import ActiveSkillSnapshot
from src.memory.skill_store import SkillVersionRecord, SkillVersionStore
from src.memory.summary_blocks import SummaryBlockRecord, SummaryBlockRepository


@dataclass(frozen=True)
class _UsageStats:
    times_loaded: int = 0
    times_used: int = 0


class MemoryRetrievalSource(Protocol):
    source_name: RetrievalSourceName
    memory_kind: RetrievalMemoryKind

    def retrieve(self, request: RetrievalRequest) -> RetrievalSourceResult:
        ...


def _candidate_id(memory_kind: str, record_id: str) -> str:
    return f"{memory_kind}:{record_id}"


def _text_token_count(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


def _fields_matched(query: str, fields: Dict[str, Any]) -> Tuple[str, ...]:
    if not query:
        return tuple()
    matched = []
    for name, value in fields.items():
        text = " ".join(str(item) for item in value) if isinstance(value, list) else str(value or "")
        if lexical_similarity(query, text) > 0:
            matched.append(str(name))
    return tuple(matched)


def _score(
    *,
    components: Dict[str, float],
    weights: Dict[str, float],
    strategy: str,
) -> RetrievalScore:
    clamped_components = {key: clamp_score(value) for key, value in components.items()}
    raw = weighted_score(clamped_components, weights)
    return RetrievalScore(
        raw_score=raw,
        normalized_score=raw,
        rank_score=raw,
        components=clamped_components,
        strategy=strategy,
    )


def _created_newest(records: Iterable[Any]) -> Optional[str]:
    values = [str(getattr(record, "created_at", "") or "") for record in records]
    values = [value for value in values if value]
    return max(values) if values else None


class SummaryBlockRetrievalSource:
    source_name: RetrievalSourceName = "summary_blocks"
    memory_kind: RetrievalMemoryKind = "summary"

    def __init__(self, db_path: Optional[Path] = None, repository: Optional[SummaryBlockRepository] = None):
        self.repository = repository or SummaryBlockRepository(db_path=db_path)

    def retrieve(self, request: RetrievalRequest) -> RetrievalSourceResult:
        if not request.session_id or request.per_source_limit <= 0:
            return RetrievalSourceResult(self.source_name, self.memory_kind)
        records = self.repository.list_summary_blocks(
            session_id=request.session_id,
            limit=max(request.per_source_limit * 3, request.per_source_limit),
            newest_first=True,
        )
        newest = _created_newest(records)
        candidates = [self._candidate(record, request, newest) for record in records]
        ranked = rank_candidates(normalize_candidates(candidates))[: request.per_source_limit]
        return RetrievalSourceResult(self.source_name, self.memory_kind, tuple(ranked))

    def _candidate(
        self,
        record: SummaryBlockRecord,
        request: RetrievalRequest,
        newest_at: Optional[str],
    ) -> RetrievedMemoryCandidate:
        title = f"Summary block {record.sequence_number}"
        coverage = clamp_score((record.original_token_count or record.token_count or 0) / 4000.0)
        components = {
            "lexical": lexical_similarity(request.query, record.summary),
            "recency": recency_score(record.created_at, newest_at=newest_at),
            "coverage": coverage,
        }
        content = record.summary
        score = _score(
            components=components,
            weights={"lexical": 0.70, "recency": 0.20, "coverage": 0.10},
            strategy="summary_lexical_recency",
        )
        provenance = RetrievalProvenance(
            source_name=self.source_name,
            table_name="summary_blocks",
            record_id=record.id,
            session_id=record.session_id,
            created_at=record.created_at,
            fields_matched=_fields_matched(request.query, {"summary": record.summary}),
            source_module="src.memory.summary_blocks",
            metadata={
                "sequence_number": record.sequence_number,
                "covered_message_ids": list(record.covered_message_ids),
                "start_message_id": record.start_message_id,
                "end_message_id": record.end_message_id,
                "source_job_id": record.source_job_id,
                "model_provider": record.model_provider,
                "model_name": record.model_name,
                "original_token_count": record.original_token_count,
            },
        )
        return RetrievedMemoryCandidate(
            id=_candidate_id("summary", record.id),
            memory_kind=self.memory_kind,
            title=title,
            content=content,
            token_count=record.token_count or _text_token_count(content),
            score=score,
            provenance=provenance,
            debug={"components": dict(score.components)} if request.include_debug else {},
        )


class StructuredEpisodeRetrievalSource:
    source_name: RetrievalSourceName = "structured_episodes"
    memory_kind: RetrievalMemoryKind = "episodic"

    def __init__(self, db_path: Optional[Path] = None, repository: Optional[StructuredEpisodeRepository] = None):
        self.repository = repository or StructuredEpisodeRepository(db_path=db_path)

    def retrieve(self, request: RetrievalRequest) -> RetrievalSourceResult:
        if request.per_source_limit <= 0:
            return RetrievalSourceResult(self.source_name, self.memory_kind)
        records = self._records(request)
        newest = _created_newest(records)
        candidates = [self._candidate(record, request, newest) for record in records]
        ranked = rank_candidates(normalize_candidates(candidates))[: request.per_source_limit]
        return RetrievalSourceResult(self.source_name, self.memory_kind, tuple(ranked))

    def _records(self, request: RetrievalRequest) -> List[StructuredEpisodeRecord]:
        limit = max(request.per_source_limit * 4, request.per_source_limit)
        records: List[StructuredEpisodeRecord] = []
        if request.query:
            records = self.repository.search_text(request.query, session_id=request.session_id, limit=limit)
        if request.session_id:
            existing_ids = {record.id for record in records}
            fallback = self.repository.list_by_session(request.session_id, limit=limit, newest_first=True)
            records.extend(record for record in fallback if record.id not in existing_ids)
        return records[:limit]

    def _candidate(
        self,
        record: StructuredEpisodeRecord,
        request: RetrievalRequest,
        newest_at: Optional[str],
    ) -> RetrievedMemoryCandidate:
        content = _episode_content(record)
        fields = {
            "title": record.title,
            "summary": record.summary,
            "participants": record.participants,
            "goals": record.goals,
            "decisions": record.decisions,
            "artifacts": record.artifacts,
            "topics": record.topics,
        }
        components = {
            "lexical": lexical_similarity(request.query, content),
            "topic_overlap": lexical_similarity(request.query, " ".join(record.topics + record.goals + record.artifacts)),
            "importance": clamp_score(record.importance),
            "recency": recency_score(record.created_at, newest_at=newest_at),
        }
        score = _score(
            components=components,
            weights={"lexical": 0.55, "topic_overlap": 0.20, "importance": 0.15, "recency": 0.10},
            strategy="structured_episode_lexical",
        )
        provenance = RetrievalProvenance(
            source_name=self.source_name,
            table_name="structured_episodes",
            record_id=record.id,
            session_id=record.session_id,
            created_at=record.created_at,
            fields_matched=_fields_matched(request.query, fields),
            source_module="src.memory.episode_store",
            metadata={
                "action": record.action,
                "topics": list(record.topics),
                "source_job_id": record.source_job_id,
                "start_message_id": record.start_message_id,
                "end_message_id": record.end_message_id,
                "parent_episode_id": record.parent_episode_id,
                "importance": record.importance,
            },
        )
        return RetrievedMemoryCandidate(
            id=_candidate_id("episodic", record.id),
            memory_kind=self.memory_kind,
            title=record.title,
            content=content,
            token_count=_text_token_count(content),
            score=score,
            provenance=provenance,
            debug={"components": dict(score.components)} if request.include_debug else {},
        )


class SemanticFactRetrievalSource:
    source_name: RetrievalSourceName = "semantic_facts"
    memory_kind: RetrievalMemoryKind = "semantic"

    def __init__(
        self,
        db_path: Optional[Path] = None,
        store: Optional[SemanticFactStore] = None,
        embedding_store: Optional[SemanticEmbeddingStore] = None,
    ):
        self.store = store or SemanticFactStore(db_path=db_path)
        self.embedding_store = embedding_store or SemanticEmbeddingStore(db_path=db_path)

    def retrieve(self, request: RetrievalRequest) -> RetrievalSourceResult:
        if request.per_source_limit <= 0:
            return RetrievalSourceResult(self.source_name, self.memory_kind)
        facts = self.store.list_facts()
        newest = _created_newest(facts)
        query_vector = None
        if request.query:
            try:
                query_vector = get_embedding_provider().embed_text(request.query)
            except Exception:
                query_vector = None
        candidates = [self._candidate(fact, request, newest, query_vector) for fact in facts]
        ranked = rank_candidates(normalize_candidates(candidates))[: request.per_source_limit]
        return RetrievalSourceResult(self.source_name, self.memory_kind, tuple(ranked))

    def _candidate(
        self,
        fact: SemanticFactRecord,
        request: RetrievalRequest,
        newest_at: Optional[str],
        query_vector: Any,
    ) -> RetrievedMemoryCandidate:
        content = canonical_semantic_fact_text(fact.category, fact.fact_text, fact.source)
        embedding_score = 0.0
        strategy = "lexical_fallback"
        embedding_model = None
        if query_vector is not None:
            embedding_model = getattr(query_vector, "model", DEFAULT_EMBEDDING_MODEL)
            embedding = self.embedding_store.get_embedding(
                SEMANTIC_FACT_OWNER_TYPE,
                str(fact.id),
                embedding_model,
            )
            if embedding is not None:
                embedding_score = clamp_score((cosine_similarity(query_vector.values, embedding.embedding) + 1.0) / 2.0)
                strategy = "existing_embedding"
        lexical = lexical_similarity(request.query, content)
        base_similarity = max(lexical, embedding_score)
        components = {
            "similarity": base_similarity,
            "lexical": lexical,
            "embedding": embedding_score,
            "confidence": clamp_score(fact.confidence),
            "recency": recency_score(fact.created_at, newest_at=newest_at),
        }
        score = _score(
            components=components,
            weights={"similarity": 0.65, "confidence": 0.25, "recency": 0.10},
            strategy=strategy,
        )
        provenance = RetrievalProvenance(
            source_name=self.source_name,
            table_name="facts",
            record_id=str(fact.id),
            session_id=None,
            created_at=fact.created_at,
            fields_matched=_fields_matched(request.query, {"category": fact.category, "fact_text": fact.fact_text, "source": fact.source}),
            source_module="src.memory.semantic_store",
            metadata={
                "category": fact.category,
                "source": fact.source,
                "confidence": fact.confidence,
                "embedding_model": embedding_model,
                "embedding_used": embedding_score > 0,
            },
        )
        return RetrievedMemoryCandidate(
            id=_candidate_id("semantic", str(fact.id)),
            memory_kind=self.memory_kind,
            title=fact.category,
            content=fact.fact_text,
            token_count=_text_token_count(fact.fact_text),
            score=score,
            provenance=provenance,
            debug={"components": dict(score.components)} if request.include_debug else {},
        )


class ProceduralSkillRetrievalSource:
    source_name: RetrievalSourceName = "procedural_skills"
    memory_kind: RetrievalMemoryKind = "procedural"

    def __init__(
        self,
        db_path: Optional[Path] = None,
        store: Optional[SkillVersionStore] = None,
        snapshot_skills: Optional[Sequence[ActiveSkillSnapshot]] = None,
    ):
        self.db_path = db_path
        self.store = store or SkillVersionStore(db_path=db_path)
        self.snapshot_skills = tuple(snapshot_skills) if snapshot_skills is not None else None

    def retrieve(self, request: RetrievalRequest) -> RetrievalSourceResult:
        if request.per_source_limit <= 0:
            return RetrievalSourceResult(self.source_name, self.memory_kind)
        usage_stats = _read_usage_stats(self.db_path)
        items = self._records_or_snapshot()
        candidates = [self._candidate(item, request, usage_stats) for item in items]
        ranked = rank_candidates(normalize_candidates(candidates))[: request.per_source_limit]
        return RetrievalSourceResult(self.source_name, self.memory_kind, tuple(ranked))

    def _records_or_snapshot(self) -> Sequence[SkillVersionRecord | ActiveSkillSnapshot]:
        if self.snapshot_skills is not None:
            return self.snapshot_skills
        return [record for record in self.store.list_active_versions() if record.enabled and record.active and not record.archived_at]

    def _candidate(
        self,
        item: SkillVersionRecord | ActiveSkillSnapshot,
        request: RetrievalRequest,
        usage_stats: Dict[str, _UsageStats],
    ) -> RetrievedMemoryCandidate:
        if isinstance(item, SkillVersionRecord):
            record_id = item.id
            skill_id = item.skill_id
            name = item.name
            description = item.description
            preferred_tools = list(item.preferred_tools)
            tags = list(item.tags)
            workflow = str(item.workflow.get("execution_steps") or "")
            keywords = [str(keyword) for keyword in item.frontmatter.get("trigger_keywords", [])]
            confidence = item.confidence if item.confidence is not None else 1.0
            created_at = item.created_at
            metadata = {
                "skill_id": item.skill_id,
                "version": item.version,
                "version_id": item.id,
                "candidate_id": item.candidate_id,
                "file_path": item.file_path,
                "content_hash": item.content_hash,
                "preferred_tools": preferred_tools,
                "tags": tags,
                "author": item.author,
            }
        else:
            record_id = item.version_id
            skill_id = item.skill_id
            name = item.name
            description = item.description
            preferred_tools = list(item.preferred_tools)
            tags = list(item.tags)
            workflow = item.execution_steps
            keywords = list(item.trigger_keywords)
            confidence = 1.0
            created_at = None
            metadata = {
                "skill_id": item.skill_id,
                "version_id": item.version_id,
                "file_path": item.file_path,
                "content_hash": item.content_hash,
                "preferred_tools": preferred_tools,
                "tags": tags,
                "from_snapshot": True,
            }
        content = _skill_content(name, description, keywords, preferred_tools, tags, workflow)
        stats = usage_stats.get(skill_id, _UsageStats())
        usage = clamp_score((stats.times_used + (0.25 * stats.times_loaded)) / 20.0)
        components = {
            "lexical": lexical_similarity(request.query, content),
            "tools": lexical_similarity(request.query, " ".join(preferred_tools)),
            "tags": lexical_similarity(request.query, " ".join(tags + keywords)),
            "confidence": clamp_score(confidence),
            "usage": usage,
        }
        score = _score(
            components=components,
            weights={"lexical": 0.50, "tags": 0.20, "tools": 0.10, "confidence": 0.10, "usage": 0.10},
            strategy="procedural_skill_lexical_usage",
        )
        provenance = RetrievalProvenance(
            source_name=self.source_name,
            table_name="skill_versions",
            record_id=record_id,
            session_id=None,
            created_at=created_at,
            fields_matched=_fields_matched(
                request.query,
                {
                    "name": name,
                    "description": description,
                    "trigger_keywords": keywords,
                    "preferred_tools": preferred_tools,
                    "tags": tags,
                    "execution_steps": workflow,
                },
            ),
            source_module="src.memory.skill_store",
            metadata={**metadata, "times_loaded": stats.times_loaded, "times_used": stats.times_used},
        )
        return RetrievedMemoryCandidate(
            id=_candidate_id("procedural", record_id),
            memory_kind=self.memory_kind,
            title=name,
            content=content,
            token_count=_text_token_count(content),
            score=score,
            provenance=provenance,
            debug={"components": dict(score.components)} if request.include_debug else {},
        )


def _episode_content(record: StructuredEpisodeRecord) -> str:
    lines = [f"Title: {record.title}", f"Summary: {record.summary}"]
    if record.participants:
        lines.append(f"Participants: {', '.join(record.participants)}")
    if record.goals:
        lines.append(f"Goals: {'; '.join(record.goals)}")
    if record.decisions:
        lines.append(f"Decisions: {'; '.join(record.decisions)}")
    if record.artifacts:
        lines.append(f"Artifacts: {'; '.join(record.artifacts)}")
    if record.topics:
        lines.append(f"Topics: {', '.join(record.topics)}")
    return "\n".join(lines)


def _skill_content(
    name: str,
    description: str,
    trigger_keywords: Sequence[str],
    preferred_tools: Sequence[str],
    tags: Sequence[str],
    workflow: str,
) -> str:
    lines = [f"Name: {name}", f"Description: {description}"]
    if trigger_keywords:
        lines.append(f"Trigger keywords: {', '.join(trigger_keywords)}")
    if preferred_tools:
        lines.append(f"Preferred tools: {', '.join(preferred_tools)}")
    if tags:
        lines.append(f"Tags: {', '.join(tags)}")
    if workflow:
        lines.append(f"Workflow: {workflow}")
    return "\n".join(lines)


def _read_usage_stats(db_path: Optional[Path]) -> Dict[str, _UsageStats]:
    conn = get_connection(db_path)
    try:
        rows = conn.execute("SELECT skill_id, times_loaded, times_used FROM skill_usage_stats").fetchall()
        return {
            str(row["skill_id"]): _UsageStats(
                times_loaded=int(row["times_loaded"] or 0),
                times_used=int(row["times_used"] or 0),
            )
            for row in rows
        }
    finally:
        conn.close()


def retrieve_summary_blocks(request: RetrievalRequest, *, db_path: Optional[Path] = None) -> RetrievalSourceResult:
    return SummaryBlockRetrievalSource(db_path=db_path).retrieve(request)


def retrieve_structured_episodes(request: RetrievalRequest, *, db_path: Optional[Path] = None) -> RetrievalSourceResult:
    return StructuredEpisodeRetrievalSource(db_path=db_path).retrieve(request)


def retrieve_semantic_facts(request: RetrievalRequest, *, db_path: Optional[Path] = None) -> RetrievalSourceResult:
    return SemanticFactRetrievalSource(db_path=db_path).retrieve(request)


def retrieve_procedural_skills(request: RetrievalRequest, *, db_path: Optional[Path] = None) -> RetrievalSourceResult:
    return ProceduralSkillRetrievalSource(db_path=db_path).retrieve(request)


def _default_sources(db_path: Optional[Path]) -> Tuple[MemoryRetrievalSource, ...]:
    return (
        SemanticFactRetrievalSource(db_path=db_path),
        StructuredEpisodeRetrievalSource(db_path=db_path),
        ProceduralSkillRetrievalSource(db_path=db_path),
        SummaryBlockRetrievalSource(db_path=db_path),
    )


def retrieve_all_sources(
    request: RetrievalRequest,
    *,
    db_path: Optional[Path] = None,
    sources: Optional[Sequence[MemoryRetrievalSource]] = None,
) -> RetrievalBundle:
    selected_sources = tuple(sources) if sources is not None else _default_sources(db_path)
    source_results: List[RetrievalSourceResult] = []
    all_candidates: List[RetrievedMemoryCandidate] = []
    requested_kinds = set(request.memory_kinds)
    for source in selected_sources:
        if source.memory_kind not in requested_kinds:
            continue
        try:
            result = source.retrieve(request)
        except Exception as exc:
            result = RetrievalSourceResult(
                source_name=source.source_name,
                memory_kind=source.memory_kind,
                candidates=tuple(),
                errors=(f"{type(exc).__name__}: {exc}",),
            )
        source_results.append(result)
        all_candidates.extend(result.candidates)

    ranked = rank_candidates(all_candidates)
    if request.token_budget is not None:
        kept, omitted, total_tokens = trim_retrieval_candidates_to_budget(
            ranked,
            request.token_budget,
            provider=request.provider,
            model_name=request.model_name,
        )
    else:
        kept = tuple(ranked)
        omitted = tuple()
        total_tokens = sum(
            candidate.token_count
            or estimate_retrieval_candidate_tokens(
                candidate,
                provider=request.provider,
                model_name=request.model_name,
            )
            for candidate in kept
        )
    return RetrievalBundle(
        request=request,
        source_results=tuple(source_results),
        candidates=tuple(kept),
        omitted_candidate_ids=tuple(omitted),
        total_tokens=total_tokens,
    )
