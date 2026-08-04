import json

from src.memory.context_assembler import (
    ContextAssemblyOptions,
    assemble_retrieved_memory_context,
    candidate_to_legacy_retrieved_item,
    format_candidate_for_context,
)
from src.memory.retrieval_types import (
    RetrievedMemoryCandidate,
    RetrievalBundle,
    RetrievalProvenance,
    RetrievalRequest,
    RetrievalScore,
)


def _source_for(kind):
    return {
        "semantic": ("semantic_facts", "facts"),
        "episodic": ("structured_episodes", "structured_episodes"),
        "procedural": ("procedural_skills", "skill_versions"),
        "summary": ("summary_blocks", "summary_blocks"),
    }[kind]


def _candidate(kind, candidate_id, content="content", title="Title", metadata=None, token_count=4):
    source, table = _source_for(kind)
    return RetrievedMemoryCandidate(
        id=f"{kind}:{candidate_id}",
        memory_kind=kind,
        title=title,
        content=content,
        token_count=token_count,
        score=RetrievalScore(raw_score=1, normalized_score=1, rank_score=1, components={"lexical": 1}, strategy="test"),
        provenance=RetrievalProvenance(
            source_name=source,
            table_name=table,
            record_id=candidate_id,
            session_id="sess" if kind in {"summary", "episodic"} else None,
            created_at="2026-01-01T00:00:00Z",
            fields_matched=("content",),
            source_module="test",
            metadata=metadata or {},
        ),
        debug={"secret_debug": True},
    )


def _bundle(candidates):
    return RetrievalBundle(
        request=RetrievalRequest(query="test", session_id="sess"),
        candidates=tuple(candidates),
        omitted_candidate_ids=tuple(),
        total_tokens=sum(candidate.token_count for candidate in candidates),
    )


def test_empty_bundle_returns_empty_block():
    assembled = assemble_retrieved_memory_context(_bundle([]), ContextAssemblyOptions(total_token_budget=100))

    assert assembled.block_text == ""
    assert assembled.legacy_retrieved_items == []
    assert assembled.included_candidate_ids == tuple()


def test_assembler_keeps_legacy_header_and_sections():
    candidates = [
        _candidate("semantic", "1", "User prefers FastAPI", "profile", {"category": "profile"}),
        _candidate("episodic", "2", "Designed retrieval planner", "Planner design", {"action": "CREATE"}),
        _candidate("procedural", "3", "Workflow: Deploy staging", "Deploy Staging", {"skill_id": "deploy-staging"}),
        _candidate("summary", "4", "Older project context", "Summary", {"sequence_number": 2}),
    ]

    assembled = assemble_retrieved_memory_context(_bundle(candidates), ContextAssemblyOptions(total_token_budget=500))

    assert assembled.block_text.startswith("[Retrieved Long-Term Memory]\n")
    assert "Semantic Facts:" in assembled.block_text
    assert "Past Episodes:" in assembled.block_text
    assert "Procedural Skills:" in assembled.block_text
    assert "Conversation Summaries:" in assembled.block_text
    assert "- [profile] User prefers FastAPI" in assembled.block_text
    assert "- Skill 'Deploy Staging':" in assembled.block_text


def test_total_and_per_kind_budget_are_respected():
    candidates = [
        _candidate("semantic", "1", "a" * 80, "profile", {"category": "profile"}, token_count=20),
        _candidate("semantic", "2", "b" * 80, "profile", {"category": "profile"}, token_count=20),
        _candidate("episodic", "3", "c" * 80, "episode", token_count=20),
    ]

    assembled = assemble_retrieved_memory_context(
        _bundle(candidates),
        ContextAssemblyOptions(total_token_budget=75, budget_by_kind={"semantic": 40, "episodic": 35}),
    )

    assert assembled.token_count <= 75
    assert assembled.included_candidate_ids == ("semantic:1", "episodic:3")
    assert "semantic:2" in assembled.omitted_candidate_ids


def test_debug_metadata_is_not_in_block_text():
    candidate = _candidate("semantic", "1", "User prefers pytest", "profile", {"category": "profile"})

    assembled = assemble_retrieved_memory_context(
        _bundle([candidate]),
        ContextAssemblyOptions(total_token_budget=100, include_debug=True),
    )

    assert "secret_debug" not in assembled.block_text
    assert "components" not in assembled.block_text
    assert "source_module" not in assembled.block_text
    assert assembled.debug


def test_legacy_retrieved_items_are_json_serializable():
    candidate = _candidate("summary", "4", "Older project context", "Summary", {"sequence_number": 2})

    item = candidate_to_legacy_retrieved_item(candidate)
    formatted = format_candidate_for_context(candidate)

    assert json.loads(json.dumps(item))["summary"] == "Older project context"
    assert formatted.startswith("- Summary block 2:")
