from dataclasses import dataclass, field
from typing import Any, Dict, Literal, Optional, Tuple


RetrievalMemoryKind = Literal["summary", "episodic", "semantic", "procedural"]
RetrievalSourceName = Literal[
    "summary_blocks",
    "structured_episodes",
    "semantic_facts",
    "procedural_skills",
]

VALID_MEMORY_KINDS = ("semantic", "episodic", "procedural", "summary")
VALID_SOURCE_NAMES = (
    "summary_blocks",
    "structured_episodes",
    "semantic_facts",
    "procedural_skills",
)


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _clamp(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    if parsed < 0.0:
        return 0.0
    if parsed > 1.0:
        return 1.0
    return parsed


@dataclass(frozen=True)
class RetrievalRequest:
    query: str
    session_id: Optional[str] = None
    memory_kinds: Tuple[RetrievalMemoryKind, ...] = VALID_MEMORY_KINDS  # type: ignore[assignment]
    per_source_limit: int = 5
    token_budget: Optional[int] = None
    provider: str = "openai"
    model_name: str = "gpt-4o-mini"
    include_debug: bool = False

    def __post_init__(self) -> None:
        kinds = tuple(str(kind) for kind in self.memory_kinds)
        invalid = [kind for kind in kinds if kind not in VALID_MEMORY_KINDS]
        if invalid:
            raise ValueError(f"unknown retrieval memory kind: {invalid[0]}")
        budget = None if self.token_budget is None else max(0, int(self.token_budget))
        object.__setattr__(self, "query", _clean_text(self.query))
        object.__setattr__(self, "session_id", _clean_text(self.session_id) or None)
        object.__setattr__(self, "memory_kinds", kinds)
        object.__setattr__(self, "per_source_limit", max(0, int(self.per_source_limit)))
        object.__setattr__(self, "token_budget", budget)
        object.__setattr__(self, "provider", _clean_text(self.provider) or "openai")
        object.__setattr__(self, "model_name", _clean_text(self.model_name) or "gpt-4o-mini")


@dataclass(frozen=True)
class RetrievalScore:
    raw_score: float = 0.0
    normalized_score: float = 0.0
    rank_score: float = 0.0
    components: Dict[str, float] = field(default_factory=dict)
    strategy: str = "lexical"

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw_score", _clamp(self.raw_score))
        object.__setattr__(self, "normalized_score", _clamp(self.normalized_score))
        object.__setattr__(self, "rank_score", _clamp(self.rank_score))
        object.__setattr__(
            self,
            "components",
            {str(key): _clamp(value) for key, value in dict(self.components).items()},
        )
        object.__setattr__(self, "strategy", _clean_text(self.strategy) or "lexical")


@dataclass(frozen=True)
class RetrievalProvenance:
    source_name: RetrievalSourceName
    table_name: str
    record_id: str
    session_id: Optional[str]
    created_at: Optional[str]
    fields_matched: Tuple[str, ...] = tuple()
    source_module: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        source = str(self.source_name)
        if source not in VALID_SOURCE_NAMES:
            raise ValueError(f"unknown retrieval source: {source}")
        object.__setattr__(self, "source_name", source)
        object.__setattr__(self, "table_name", _clean_text(self.table_name))
        object.__setattr__(self, "record_id", _clean_text(self.record_id))
        object.__setattr__(self, "session_id", _clean_text(self.session_id) or None)
        object.__setattr__(self, "created_at", _clean_text(self.created_at) or None)
        object.__setattr__(self, "fields_matched", tuple(str(item) for item in self.fields_matched))
        object.__setattr__(self, "source_module", _clean_text(self.source_module))
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True)
class RetrievedMemoryCandidate:
    id: str
    memory_kind: RetrievalMemoryKind
    title: str
    content: str
    token_count: int
    score: RetrievalScore
    provenance: RetrievalProvenance
    debug: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        kind = str(self.memory_kind)
        if kind not in VALID_MEMORY_KINDS:
            raise ValueError(f"unknown retrieval memory kind: {kind}")
        object.__setattr__(self, "id", _clean_text(self.id))
        object.__setattr__(self, "memory_kind", kind)
        object.__setattr__(self, "title", _clean_text(self.title))
        object.__setattr__(self, "content", str(self.content or "").strip())
        object.__setattr__(self, "token_count", max(0, int(self.token_count)))
        object.__setattr__(self, "debug", dict(self.debug))


@dataclass(frozen=True)
class RetrievalSourceResult:
    source_name: RetrievalSourceName
    memory_kind: RetrievalMemoryKind
    candidates: Tuple[RetrievedMemoryCandidate, ...] = tuple()
    errors: Tuple[str, ...] = tuple()

    def __post_init__(self) -> None:
        source = str(self.source_name)
        kind = str(self.memory_kind)
        if source not in VALID_SOURCE_NAMES:
            raise ValueError(f"unknown retrieval source: {source}")
        if kind not in VALID_MEMORY_KINDS:
            raise ValueError(f"unknown retrieval memory kind: {kind}")
        object.__setattr__(self, "source_name", source)
        object.__setattr__(self, "memory_kind", kind)
        object.__setattr__(self, "candidates", tuple(self.candidates))
        object.__setattr__(self, "errors", tuple(str(error) for error in self.errors))


@dataclass(frozen=True)
class RetrievalBundle:
    request: RetrievalRequest
    source_results: Tuple[RetrievalSourceResult, ...] = tuple()
    candidates: Tuple[RetrievedMemoryCandidate, ...] = tuple()
    omitted_candidate_ids: Tuple[str, ...] = tuple()
    total_tokens: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_results", tuple(self.source_results))
        object.__setattr__(self, "candidates", tuple(self.candidates))
        object.__setattr__(self, "omitted_candidate_ids", tuple(str(item) for item in self.omitted_candidate_ids))
        object.__setattr__(self, "total_tokens", max(0, int(self.total_tokens)))
