from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional


ModelRole = Literal["primary", "secondary"]

MemoryKind = Literal[
    "short_term",
    "episodic",
    "semantic",
    "procedural",
    "summary",
]

MemoryJobType = Literal[
    "episode_generation",
    "semantic_candidate_extraction",
    "procedural_candidate_generation",
    "semantic_consolidation",
    "procedural_consolidation",
    "skill_promotion",
    "summary_generation",
]

DedupAction = Literal["NEW", "DUPLICATE", "UPDATE", "MERGE"]
EpisodeAction = Literal["CREATE", "UPDATE", "MERGE", "SPLIT"]

SkillCandidateStatus = Literal[
    "NEW",
    "OBSERVING",
    "READY_FOR_PROMOTION",
    "WAITING_FOR_APPROVAL",
    "PROMOTED",
    "REJECTED",
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
class EpisodicMemory:
    id: str
    session_id: str
    title: str
    summary: str
    participants: List[str]
    goals: List[str]
    decisions: List[str]
    artifacts: List[str]
    topics: List[str]
    importance: float
    start_message_id: str
    end_message_id: str
    created_at: str
    source: str


@dataclass(frozen=True)
class SemanticFact:
    id: str
    category: str
    fact: str
    source: str
    confidence: float
    created_at: str
    updated_at: Optional[str] = None


@dataclass(frozen=True)
class FactCandidate:
    id: str
    session_id: str
    fact: str
    category: str
    confidence: float
    explicit: bool
    source: str
    created_at: str


@dataclass(frozen=True)
class SkillWorkflowStep:
    step_number: int
    instruction: str
    optional_tools: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class SkillCandidate:
    id: str
    title: str
    description: str
    trigger_description: str
    workflow: List[SkillWorkflowStep]
    preferred_tools: List[str]
    confidence: float
    occurrences: int
    source_episode_ids: List[str]
    created_at: str
    updated_at: str
    status: SkillCandidateStatus


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
