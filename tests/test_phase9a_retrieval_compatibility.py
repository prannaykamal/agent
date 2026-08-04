import pytest

from src.db import add_fact, init_db
from src.memory.procedural import match_procedural_skills
from src.memory.retrieval_gate import should_retrieve_memory
from src.memory.retrieval_sources import retrieve_all_sources
from src.memory.retrieval_types import RetrievalRequest
from src.memory.semantic import search_facts_top_k


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "phase9a_compat.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file


def test_existing_retrieval_gate_behavior_is_unchanged():
    assert should_retrieve_memory("hello") is False
    assert should_retrieve_memory("what do you remember about my project?") is True


def test_existing_semantic_wrapper_still_behaves(temp_db):
    add_fact("profile", "User prefers pytest", db_path=temp_db)

    results = search_facts_top_k("pytest", k=3, db_path=temp_db)

    assert results
    assert results[0]["fact_text"] == "User prefers pytest"


def test_existing_procedural_wrapper_shape_is_unchanged(temp_db):
    assert match_procedural_skills("anything", db_path=temp_db) == []


def test_retrieval_primitives_do_not_call_llm_route_helpers(temp_db, monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("retrieval primitives must not call LLM route helpers")

    monkeypatch.setattr("src.harness.llm_router.resolve_primary_llm", fail)
    monkeypatch.setattr("src.harness.llm_router.resolve_secondary_llm", fail)

    bundle = retrieve_all_sources(RetrievalRequest(query="pytest", session_id="session-a"), db_path=temp_db)

    assert bundle.candidates == tuple()
