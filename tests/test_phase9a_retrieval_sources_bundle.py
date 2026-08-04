from dataclasses import dataclass

import pytest

from src.db import add_fact, init_db
from src.memory.retrieval_sources import retrieve_all_sources
from src.memory.retrieval_types import (
    RetrievedMemoryCandidate,
    RetrievalProvenance,
    RetrievalRequest,
    RetrievalScore,
    RetrievalSourceResult,
)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "phase9a_bundle.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file


@dataclass(frozen=True)
class FailingSource:
    source_name: str = "semantic_facts"
    memory_kind: str = "semantic"

    def retrieve(self, request):
        raise RuntimeError("source exploded")


@dataclass(frozen=True)
class StaticSource:
    source_name: str = "summary_blocks"
    memory_kind: str = "summary"

    def retrieve(self, request):
        candidate = RetrievedMemoryCandidate(
            id="summary:static",
            memory_kind="summary",
            title="Static",
            content="a" * 80,
            token_count=20,
            score=RetrievalScore(raw_score=1, normalized_score=1, rank_score=1),
            provenance=RetrievalProvenance("summary_blocks", "summary_blocks", "static", request.session_id, None),
        )
        return RetrievalSourceResult("summary_blocks", "summary", (candidate,))


def test_retrieve_all_sources_isolates_source_failures(temp_db):
    bundle = retrieve_all_sources(
        RetrievalRequest(query="anything", memory_kinds=("semantic", "summary")),
        db_path=temp_db,
        sources=[FailingSource(), StaticSource()],
    )

    assert len(bundle.source_results) == 2
    assert bundle.source_results[0].errors
    assert [candidate.id for candidate in bundle.candidates] == ["summary:static"]


def test_empty_db_returns_empty_bundle(temp_db):
    bundle = retrieve_all_sources(RetrievalRequest(query="nothing", session_id="session-a"), db_path=temp_db)

    assert bundle.candidates == tuple()
    assert bundle.omitted_candidate_ids == tuple()
    assert bundle.total_tokens == 0


def test_bundle_applies_cross_source_ranking_and_token_budget(temp_db):
    add_fact("profile", "User prefers FastAPI services", db_path=temp_db)

    bundle = retrieve_all_sources(
        RetrievalRequest(query="FastAPI services", token_budget=2, per_source_limit=5),
        db_path=temp_db,
    )

    assert bundle.total_tokens <= 2
    assert bundle.omitted_candidate_ids
