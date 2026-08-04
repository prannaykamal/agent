from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from src.memory.retrieval_ranker import estimate_retrieval_candidate_tokens
from src.memory.retrieval_types import (
    RetrievedMemoryCandidate,
    RetrievalBundle,
    RetrievalMemoryKind,
)


SECTION_LABELS: Dict[RetrievalMemoryKind, str] = {
    "semantic": "Semantic Facts:",
    "episodic": "Past Episodes:",
    "procedural": "Procedural Skills:",
    "summary": "Conversation Summaries:",
}

SECTION_ORDER: Tuple[RetrievalMemoryKind, ...] = ("semantic", "episodic", "procedural", "summary")


@dataclass(frozen=True)
class ContextAssemblyOptions:
    total_token_budget: int
    budget_by_kind: Dict[RetrievalMemoryKind, int] = field(default_factory=dict)
    include_debug: bool = False
    preserve_legacy_header: bool = True
    max_items_per_kind: Optional[int] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "total_token_budget", max(0, int(self.total_token_budget)))
        object.__setattr__(
            self,
            "budget_by_kind",
            {str(kind): max(0, int(value)) for kind, value in dict(self.budget_by_kind).items()},
        )
        if self.max_items_per_kind is not None:
            object.__setattr__(self, "max_items_per_kind", max(0, int(self.max_items_per_kind)))


@dataclass(frozen=True)
class AssembledMemoryContext:
    block_text: str
    legacy_retrieved_items: List[Dict[str, Any]]
    included_candidate_ids: Tuple[str, ...]
    omitted_candidate_ids: Tuple[str, ...]
    token_count: int
    source_errors: Tuple[str, ...] = tuple()
    debug: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "legacy_retrieved_items", [dict(item) for item in self.legacy_retrieved_items])
        object.__setattr__(self, "included_candidate_ids", tuple(str(item) for item in self.included_candidate_ids))
        object.__setattr__(self, "omitted_candidate_ids", tuple(str(item) for item in self.omitted_candidate_ids))
        object.__setattr__(self, "token_count", max(0, int(self.token_count)))
        object.__setattr__(self, "source_errors", tuple(str(error) for error in self.source_errors))
        object.__setattr__(self, "debug", dict(self.debug))


def _token_count_text(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


def _created_at(candidate: RetrievedMemoryCandidate) -> str:
    return candidate.provenance.created_at or "unknown"


def format_candidate_for_context(candidate: RetrievedMemoryCandidate) -> str:
    kind = candidate.memory_kind
    metadata = candidate.provenance.metadata
    if kind == "semantic":
        category = str(metadata.get("category") or candidate.title or "General")
        return f"- [{category}] {candidate.content}"
    if kind == "episodic":
        title = candidate.title.strip()
        content = candidate.content.strip()
        if title and content and title not in content:
            return f"- {_created_at(candidate)}: {title} - {content}"
        return f"- {_created_at(candidate)}: {content or title}"
    if kind == "procedural":
        content = candidate.content.strip()
        for prefix in (f"Name: {candidate.title}\n", f"Description: "):
            if content.startswith(prefix):
                content = content[len(prefix) :].strip()
        return f"- Skill '{candidate.title}': {content}"
    if kind == "summary":
        sequence = metadata.get("sequence_number")
        label = f"Summary block {sequence}" if sequence is not None else candidate.title or "Summary block"
        return f"- {label}: {candidate.content}"
    return f"- {candidate.content}"


def candidate_to_legacy_retrieved_item(candidate: RetrievedMemoryCandidate) -> Dict[str, Any]:
    metadata = candidate.provenance.metadata
    base = {
        "id": candidate.provenance.record_id,
        "memory_kind": candidate.memory_kind,
        "source_name": candidate.provenance.source_name,
    }
    if candidate.memory_kind == "semantic":
        return {
            **base,
            "category": metadata.get("category") or candidate.title,
            "fact_text": candidate.content,
            "source": metadata.get("source", "retrieval"),
            "confidence": metadata.get("confidence", 0.0),
            "created_at": candidate.provenance.created_at,
        }
    if candidate.memory_kind == "episodic":
        return {
            **base,
            "timestamp": candidate.provenance.created_at,
            "content": candidate.content,
            "title": candidate.title,
            "action": metadata.get("action"),
        }
    if candidate.memory_kind == "procedural":
        return {
            **base,
            "name": candidate.title,
            "execution_steps": candidate.content,
            "skill_id": metadata.get("skill_id"),
            "version_id": metadata.get("version_id"),
        }
    if candidate.memory_kind == "summary":
        return {
            **base,
            "summary": candidate.content,
            "sequence_number": metadata.get("sequence_number"),
            "covered_message_ids": list(metadata.get("covered_message_ids") or []),
            "created_at": candidate.provenance.created_at,
        }
    return {**base, "content": candidate.content}


def _source_errors(bundle: RetrievalBundle) -> Tuple[str, ...]:
    errors: List[str] = []
    for result in bundle.source_results:
        for error in result.errors:
            errors.append(f"{result.source_name}: {error}")
    return tuple(errors)


def assemble_retrieved_memory_context(
    bundle: RetrievalBundle,
    options: ContextAssemblyOptions,
) -> AssembledMemoryContext:
    if not bundle.candidates or options.total_token_budget <= 0:
        return AssembledMemoryContext(
            block_text="",
            legacy_retrieved_items=[],
            included_candidate_ids=tuple(),
            omitted_candidate_ids=tuple(candidate.id for candidate in bundle.candidates),
            token_count=0,
            source_errors=_source_errors(bundle),
        )

    section_lines: Dict[RetrievalMemoryKind, List[str]] = {kind: [] for kind in SECTION_ORDER}
    included: List[str] = []
    omitted: List[str] = list(bundle.omitted_candidate_ids)
    legacy_items: List[Dict[str, Any]] = []
    per_kind_used: Dict[RetrievalMemoryKind, int] = {kind: 0 for kind in SECTION_ORDER}
    per_kind_count: Dict[RetrievalMemoryKind, int] = {kind: 0 for kind in SECTION_ORDER}
    total_used = _token_count_text("[Retrieved Long-Term Memory]\n") if options.preserve_legacy_header else 0

    for candidate in bundle.candidates:
        kind = candidate.memory_kind
        if kind not in SECTION_LABELS:
            omitted.append(candidate.id)
            continue
        if options.max_items_per_kind is not None and per_kind_count[kind] >= options.max_items_per_kind:
            omitted.append(candidate.id)
            continue
        line = format_candidate_for_context(candidate)
        line_tokens = candidate.token_count or estimate_retrieval_candidate_tokens(candidate)
        line_tokens = max(line_tokens, _token_count_text(line))
        section_overhead = _token_count_text(SECTION_LABELS[kind] + "\n") if not section_lines[kind] else 0
        kind_budget = options.budget_by_kind.get(kind, options.total_token_budget)
        if per_kind_used[kind] + section_overhead + line_tokens > kind_budget:
            omitted.append(candidate.id)
            continue
        if total_used + section_overhead + line_tokens > options.total_token_budget:
            omitted.append(candidate.id)
            continue
        section_lines[kind].append(line)
        per_kind_used[kind] += section_overhead + line_tokens
        total_used += section_overhead + line_tokens
        per_kind_count[kind] += 1
        included.append(candidate.id)
        legacy_items.append(candidate_to_legacy_retrieved_item(candidate))

    sections: List[str] = []
    for kind in SECTION_ORDER:
        if section_lines[kind]:
            sections.append(SECTION_LABELS[kind] + "\n" + "\n".join(section_lines[kind]))

    if not sections:
        return AssembledMemoryContext(
            block_text="",
            legacy_retrieved_items=[],
            included_candidate_ids=tuple(),
            omitted_candidate_ids=tuple(dict.fromkeys(omitted)),
            token_count=0,
            source_errors=_source_errors(bundle),
        )

    header = "[Retrieved Long-Term Memory]" if options.preserve_legacy_header else ""
    block_text = (header + "\n" if header else "") + "\n\n".join(sections)
    debug = {}
    if options.include_debug:
        debug = {
            "per_kind_used": dict(per_kind_used),
            "per_kind_count": dict(per_kind_count),
            "source_errors": list(_source_errors(bundle)),
        }
    return AssembledMemoryContext(
        block_text=block_text,
        legacy_retrieved_items=legacy_items,
        included_candidate_ids=tuple(included),
        omitted_candidate_ids=tuple(dict.fromkeys(omitted)),
        token_count=_token_count_text(block_text),
        source_errors=_source_errors(bundle),
        debug=debug,
    )
