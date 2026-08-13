import sqlite3

import pytest

from src.db import add_fact, init_db
from src.memory.embeddings import EmbeddingInput, SemanticEmbeddingStore, SEMANTIC_FACT_OWNER_TYPE
from src.memory.retrieval_sources import retrieve_semantic_facts
from src.memory.retrieval_types import RetrievalRequest


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "phase9a_semantic.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file


def _count(db_path, table):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def _fact_id(db_path, text):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute("SELECT rowid FROM facts WHERE fact_text = ?", (text,)).fetchone()[0]
    finally:
        conn.close()


def test_semantic_retrieval_reads_permanent_facts_without_writes(temp_db):
    add_fact("profile", "User prefers FastAPI for backend services", db_path=temp_db)
    before_embeddings = _count(temp_db, "semantic_embeddings")
    before_dedup = _count(temp_db, "semantic_dedup_events")

    result = retrieve_semantic_facts(RetrievalRequest(query="FastAPI backend", per_source_limit=3), db_path=temp_db)

    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.memory_kind == "semantic"
    assert candidate.content == "User prefers FastAPI for backend services"
    assert candidate.provenance.table_name == "facts"
    assert candidate.provenance.metadata["category"] == "profile"
    assert _count(temp_db, "semantic_embeddings") == before_embeddings
    assert _count(temp_db, "semantic_dedup_events") == before_dedup


def test_semantic_retrieval_ignores_deterministic_embeddings(temp_db):
    fact_text = "User prefers FastAPI for backend services"
    add_fact("profile", fact_text, db_path=temp_db)
    fact_id = _fact_id(temp_db, fact_text)
    SemanticEmbeddingStore(db_path=temp_db).upsert_embedding(
        EmbeddingInput(owner_type=SEMANTIC_FACT_OWNER_TYPE, owner_id=str(fact_id), text=fact_text)
    )
    before = _count(temp_db, "semantic_embeddings")

    result = retrieve_semantic_facts(RetrievalRequest(query="FastAPI backend", per_source_limit=3), db_path=temp_db)

    assert result.candidates
    assert result.candidates[0].score.strategy != "existing_embedding"
    assert result.candidates[0].provenance.metadata["embedding_used"] is False
    assert _count(temp_db, "semantic_embeddings") == before


def test_semantic_retrieval_does_not_modify_memory_md_or_call_upsert(temp_db, tmp_path, monkeypatch):
    add_fact("profile", "User uses pytest", db_path=temp_db)
    memory_path = tmp_path / "MEMORY.md"

    def fail_upsert(*args, **kwargs):
        raise AssertionError("retrieval must not upsert missing embeddings")

    monkeypatch.setattr(SemanticEmbeddingStore, "upsert_embedding", fail_upsert)

    result = retrieve_semantic_facts(RetrievalRequest(query="pytest"), db_path=temp_db)

    assert result.candidates
    assert not memory_path.exists()


def test_distinctive_tokens_rank_matching_facts_first(temp_db):
    add_fact("profile", "User prefers FastAPI for backend services", db_path=temp_db)
    add_fact("user_fact", "Priya's timezone is IST", db_path=temp_db)

    result = retrieve_semantic_facts(
        RetrievalRequest(query="what timezone does Priya use?", per_source_limit=3),
        db_path=temp_db,
    )

    assert result.candidates
    assert result.candidates[0].content == "Priya's timezone is IST"
    assert all("FastAPI" not in candidate.content for candidate in result.candidates)
    assert _count(temp_db, "semantic_dedup_events") == 0


def test_unrelated_facts_are_not_retrieved(temp_db):
    add_fact("profile", "User prefers FastAPI for backend services", db_path=temp_db)

    result = retrieve_semantic_facts(
        RetrievalRequest(query="what timezone does Priya use?", per_source_limit=3),
        db_path=temp_db,
    )

    assert result.candidates == tuple()
