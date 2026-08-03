import sqlite3

import pytest

from src.db import init_db
from src.memory.embeddings import (
    SEMANTIC_FACT_OWNER_TYPE,
    DeterministicFallbackEmbeddingProvider,
    EmbeddingInput,
    SemanticEmbeddingStore,
    canonical_embedding_json,
    cosine_similarity,
    get_embedding_provider,
)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "phase7b_embeddings.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file


def _count(db_path, table):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def test_deterministic_embeddings_are_stable_for_same_text():
    provider = DeterministicFallbackEmbeddingProvider()

    first = provider.embed_text("User prefers FastAPI")
    second = provider.embed_text("User prefers FastAPI")

    assert first.values == second.values
    assert first.model == "deterministic-fallback-v1"
    assert first.fallback_used is True


def test_different_text_produces_different_embedding():
    provider = DeterministicFallbackEmbeddingProvider()

    assert provider.embed_text("User prefers FastAPI").values != provider.embed_text("User prefers Django").values


def test_embedding_row_inserted_for_semantic_fact(temp_db):
    store = SemanticEmbeddingStore(db_path=temp_db)

    record = store.upsert_embedding(
        EmbeddingInput(owner_type=SEMANTIC_FACT_OWNER_TYPE, owner_id="1", text="User prefers FastAPI")
    )

    assert record.owner_type == SEMANTIC_FACT_OWNER_TYPE
    assert record.owner_id == "1"
    assert record.embedding
    assert _count(temp_db, "semantic_embeddings") == 1


def test_embedding_upsert_does_not_duplicate(temp_db):
    store = SemanticEmbeddingStore(db_path=temp_db)
    input_record = EmbeddingInput(owner_type=SEMANTIC_FACT_OWNER_TYPE, owner_id="1", text="User prefers FastAPI")

    first = store.upsert_embedding(input_record)
    second = store.upsert_embedding(input_record)

    assert first.id == second.id
    assert _count(temp_db, "semantic_embeddings") == 1


def test_cosine_similarity_and_canonical_json():
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert canonical_embedding_json([0.25, 1]) == "[0.25,1.0]"


def test_embedding_helpers_do_not_call_llms(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("LLM factory should not be called by embeddings")

    monkeypatch.setattr("src.harness.models.get_model_instance", fail)

    provider = get_embedding_provider()
    vector = provider.embed_text("User prefers deterministic tests")

    assert vector.values
