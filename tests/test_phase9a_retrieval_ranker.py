from src.memory.retrieval_ranker import (
    clamp_score,
    lexical_similarity,
    normalize_candidates,
    normalize_retrieval_text,
    rank_candidates,
    tokenize_retrieval_text,
    trim_retrieval_candidates_to_budget,
    weighted_score,
)
from src.memory.retrieval_types import RetrievedMemoryCandidate, RetrievalProvenance, RetrievalScore


def _candidate(candidate_id, kind, raw, created_at="2026-01-01T00:00:00Z", content="abcdefghij"):
    source = {
        "semantic": "semantic_facts",
        "episodic": "structured_episodes",
        "procedural": "procedural_skills",
        "summary": "summary_blocks",
    }[kind]
    table = {
        "semantic": "facts",
        "episodic": "structured_episodes",
        "procedural": "skill_versions",
        "summary": "summary_blocks",
    }[kind]
    return RetrievedMemoryCandidate(
        id=candidate_id,
        memory_kind=kind,
        title=candidate_id,
        content=content,
        token_count=0,
        score=RetrievalScore(raw_score=raw, normalized_score=raw, rank_score=raw),
        provenance=RetrievalProvenance(source, table, candidate_id, None, created_at),
    )


def test_text_normalization_and_tokenization_are_deterministic():
    assert normalize_retrieval_text("  Deploy,   DEPLOYS staging! ") == "deploy, deploys staging!"
    assert tokenize_retrieval_text("The deploys deploy staging staging") == ("deploy", "staging")


def test_lexical_similarity_is_stable_and_bounded():
    first = lexical_similarity("deploy staging", "Deploy the staging build")
    second = lexical_similarity("deploy staging", "Deploy the staging build")

    assert first == second
    assert 0 < first <= 1
    assert lexical_similarity("", "anything") == 0


def test_clamp_and_weighted_score():
    assert clamp_score(-3) == 0
    assert clamp_score(3) == 1
    assert weighted_score({"a": 1, "b": 0}, {"a": 3, "b": 1}) == 0.75


def test_score_normalization_with_equal_scores():
    normalized = normalize_candidates([_candidate("a", "semantic", 0.4), _candidate("b", "semantic", 0.4)])

    assert [candidate.score.normalized_score for candidate in normalized] == [1.0, 1.0]


def test_deterministic_tie_breaking_kind_created_at_and_id():
    candidates = [
        _candidate("summary-b", "summary", 0.8, "2026-01-03T00:00:00Z"),
        _candidate("episodic-a", "episodic", 0.8, "2026-01-02T00:00:00Z"),
        _candidate("semantic-z", "semantic", 0.8, "2026-01-01T00:00:00Z"),
        _candidate("semantic-a", "semantic", 0.8, "2026-01-01T00:00:00Z"),
    ]

    ranked = rank_candidates(candidates)

    assert [candidate.id for candidate in ranked] == ["semantic-a", "semantic-z", "episodic-a", "summary-b"]


def test_token_budget_trimming_preserves_ranking_order_and_whole_candidates():
    ranked = [
        _candidate("a", "semantic", 1.0, content="a" * 40),
        _candidate("b", "episodic", 0.9, content="b" * 40),
        _candidate("c", "summary", 0.8, content="c" * 40),
    ]

    kept, omitted, total = trim_retrieval_candidates_to_budget(ranked, 20)

    assert [candidate.id for candidate in kept] == ["a", "b"]
    assert omitted == ("c",)
    assert total == 20


def test_optional_truncation_records_debug_metadata():
    candidate = _candidate("a", "semantic", 1.0, content="x" * 100)

    kept, omitted, total = trim_retrieval_candidates_to_budget([candidate], 5, allow_truncation=True)

    assert omitted == tuple()
    assert total == 5
    assert kept[0].token_count == 5
    assert kept[0].debug["content_truncated"] is True
