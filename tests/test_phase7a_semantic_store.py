import sqlite3

import pytest

from src.db import init_db
from src.memory.semantic import add_semantic_fact, get_all_semantic_facts, search_facts_top_k, sync_memory_md
from src.memory.semantic_store import SemanticFactStore, SemanticFactValidationError, SemanticFactWrite


@pytest.fixture
def temp_paths(tmp_path, monkeypatch):
    db_file = tmp_path / "phase7a_semantic_store.db"
    mem_file = tmp_path / "MEMORY.md"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    monkeypatch.setattr("src.config.MEMORY_PATH", mem_file)
    init_db(db_file)
    return db_file, mem_file


def _count(db_path, table):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def test_explicit_fact_writes_to_legacy_facts_and_preserves_api_shape(temp_paths):
    db_path, mem_path = temp_paths

    add_semantic_fact(
        category="user_pref",
        fact_text="User prefers FastAPI",
        source="user_api",
        db_path=db_path,
        memory_path=mem_path,
    )

    facts = get_all_semantic_facts(db_path=db_path)
    assert len(facts) == 1
    assert set(facts[0]) == {"id", "category", "fact_text", "source", "confidence", "created_at"}
    assert facts[0]["fact_text"] == "User prefers FastAPI"
    assert _count(db_path, "pending_fact_candidates") == 0


def test_explicit_fact_syncs_memory_md_for_permanent_facts_only(temp_paths):
    db_path, mem_path = temp_paths

    SemanticFactStore(db_path=db_path, memory_path=mem_path).add_explicit_fact(
        SemanticFactWrite(category="profile", fact_text="User works in architecture", source="user_api")
    )
    content = sync_memory_md(db_path=db_path, memory_path=mem_path)

    assert "User works in architecture" in content
    assert mem_path.read_text(encoding="utf-8") == content


def test_invalid_explicit_fact_validation(temp_paths):
    db_path, mem_path = temp_paths
    store = SemanticFactStore(db_path=db_path, memory_path=mem_path)

    with pytest.raises(SemanticFactValidationError) as exc:
        store.add_explicit_fact(SemanticFactWrite(category="profile", fact_text="   ", source="user_api"))
    assert exc.value.field == "fact_text"

    with pytest.raises(SemanticFactValidationError) as exc:
        store.add_explicit_fact(
            SemanticFactWrite(category="profile", fact_text="Valid", source="user_api", explicit=False)
        )
    assert exc.value.field == "explicit"


def test_search_facts_top_k_still_uses_permanent_facts(temp_paths):
    db_path, mem_path = temp_paths
    add_semantic_fact("user_pref", "User prefers Python over Java", db_path=db_path, memory_path=mem_path)

    results = search_facts_top_k("Python", k=5, db_path=db_path)

    assert results
    assert "Python" in results[0]["fact_text"]
