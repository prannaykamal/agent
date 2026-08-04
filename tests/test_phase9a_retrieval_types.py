from dataclasses import FrozenInstanceError

import pytest

from src.memory.retrieval_types import (
    RetrievedMemoryCandidate,
    RetrievalBundle,
    RetrievalProvenance,
    RetrievalRequest,
    RetrievalScore,
    RetrievalSourceResult,
)


def _candidate(candidate_id="c1", kind="semantic", raw=0.5):
    return RetrievedMemoryCandidate(
        id=candidate_id,
        memory_kind=kind,
        title="Title",
        content="Some memory content",
        token_count=3,
        score=RetrievalScore(raw_score=raw, normalized_score=raw, rank_score=raw),
        provenance=RetrievalProvenance(
            source_name="semantic_facts" if kind == "semantic" else "summary_blocks",
            table_name="facts" if kind == "semantic" else "summary_blocks",
            record_id="1",
            session_id=None,
            created_at="2026-01-01T00:00:00Z",
        ),
    )


def test_retrieval_request_defaults_and_normalization():
    request = RetrievalRequest(query="  Project   Alpha  ", session_id=" sess ", per_source_limit=-1, token_budget=-2)

    assert request.query == "Project Alpha"
    assert request.session_id == "sess"
    assert request.memory_kinds == ("semantic", "episodic", "procedural", "summary")
    assert request.per_source_limit == 0
    assert request.token_budget == 0
    assert request.provider == "openai"


def test_invalid_memory_kind_fails_closed():
    with pytest.raises(ValueError):
        RetrievalRequest(query="x", memory_kinds=("unknown",))


def test_score_components_are_clamped():
    score = RetrievalScore(raw_score=2, normalized_score=-1, rank_score=0.4, components={"a": 3, "b": -7})

    assert score.raw_score == 1.0
    assert score.normalized_score == 0.0
    assert score.rank_score == 0.4
    assert score.components == {"a": 1.0, "b": 0.0}


def test_dataclasses_are_frozen_enough_for_primitives():
    candidate = _candidate()

    with pytest.raises(FrozenInstanceError):
        candidate.id = "other"  # type: ignore[misc]


def test_source_result_and_bundle_defaults():
    request = RetrievalRequest(query="alpha")
    candidate = _candidate()
    result = RetrievalSourceResult("semantic_facts", "semantic", [candidate], errors=["boom"])
    bundle = RetrievalBundle(request=request, source_results=[result], candidates=[candidate], omitted_candidate_ids=["x"], total_tokens=-1)

    assert result.candidates == (candidate,)
    assert result.errors == ("boom",)
    assert bundle.source_results == (result,)
    assert bundle.omitted_candidate_ids == ("x",)
    assert bundle.total_tokens == 0
