from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional


ModelRole = Literal["primary", "secondary"]

MemoryKind = Literal[
    "short_term",
    "summary",
    "long_term",
]

MemoryJobType = Literal[
    "summary_generation",
    "cognee_ingest",
    "memory_session_write",
    "memory_session_merge",
]


@dataclass(frozen=True)
class SummaryBlock:
    id: str
    session_id: str
    summary: str
    covered_message_ids: List[str]
    token_count: int
    created_at: str


@dataclass(frozen=True)
class RetrievalRequest:
    session_id: str
    query: str
    task_type: Optional[str]
    token_budget: int
    memory_kinds: List[MemoryKind]


@dataclass(frozen=True)
class RetrievedMemory:
    id: str
    memory_kind: MemoryKind
    content: str
    score: float
    token_count: int
    metadata: Dict[str, Any] = field(default_factory=dict)
