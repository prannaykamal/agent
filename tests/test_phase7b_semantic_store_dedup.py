import sqlite3

import pytest

from src.db import init_db
from src.memory.semantic import add_semantic_fact, get_all_semantic_facts
from src.memory.semantic_candidates import PendingFactCandidateStore, PendingFactCandidateWrite
from src.memory.semantic_store import SemanticFactStore, SemanticFactWrite


@pytest.fixture
def temp_paths(tmp_path, monkeypatch):
    db_file = tmp_path / "phase7b_store.db"
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


def _rows(db_path, table):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in conn.execute(f"SELECT rowid, * FROM {table}").fetchall()]
    finally:
        conn.close()


def test_new_creates_fact_embedding_dedup_event_and_memory_entry(temp_paths):
    db_path, mem_path = temp_paths

    add_semantic_fact("user_pref", "User prefers FastAPI", db_path=db_path, memory_path=mem_path)

    assert _count(db_path, "facts") == 1
    assert _count(db_path, "semantic_embeddings") == 1
    assert _count(db_path, "semantic_dedup_events") == 1
    assert "User prefers FastAPI" in mem_path.read_text(encoding="utf-8")


def test_duplicate_creates_no_duplicate_fact_but_records_event(temp_paths):
    db_path, mem_path = temp_paths

    add_semantic_fact("user_pref", "User prefers FastAPI", db_path=db_path, memory_path=mem_path)
    add_semantic_fact("user_pref", "User prefers FastAPI", db_path=db_path, memory_path=mem_path)

    assert _count(db_path, "facts") == 1
    assert _count(db_path, "semantic_embeddings") == 1
    assert _count(db_path, "semantic_dedup_events") == 2
    assert mem_path.read_text(encoding="utf-8").count("User prefers FastAPI") == 1


def test_update_modifies_one_row_and_regenerates_embedding(temp_paths):
    db_path, mem_path = temp_paths
    store = SemanticFactStore(db_path=db_path, memory_path=mem_path)

    first = store.add_explicit_fact(SemanticFactWrite("user_pref", "User prefers Python", source="user_api"))
    updated = store.add_explicit_fact(
        SemanticFactWrite("user_pref", "User prefers Python for backend services", source="user_api")
    )

    facts = get_all_semantic_facts(db_path=db_path)
    embeddings = _rows(db_path, "semantic_embeddings")
    events = _rows(db_path, "semantic_dedup_events")

    assert first.id == updated.id
    assert _count(db_path, "facts") == 1
    assert facts[0]["fact_text"] == "User prefers Python for backend services"
    assert len(embeddings) == 1
    assert embeddings[0]["owner_id"] == str(first.id)
    assert any(event["action"] == "UPDATE" for event in events)


def test_merge_removes_duplicate_rows_and_removed_embeddings(temp_paths):
    db_path, mem_path = temp_paths
    store = SemanticFactStore(db_path=db_path, memory_path=mem_path)
    first = store.add_explicit_fact(SemanticFactWrite("user_pref", "User prefers Python", source="user_api"))
    second = store.add_explicit_fact(SemanticFactWrite("user_pref", "User prefers FastAPI", source="user_api"))

    merged = store.add_explicit_fact(
        SemanticFactWrite("user_pref", "User prefers Python and FastAPI for backend services", source="user_api")
    )

    facts = get_all_semantic_facts(db_path=db_path)
    embedding_owner_ids = {row["owner_id"] for row in _rows(db_path, "semantic_embeddings")}
    events = _rows(db_path, "semantic_dedup_events")

    assert _count(db_path, "facts") == 1
    assert merged.id in {first.id, second.id}
    assert embedding_owner_ids == {str(merged.id)}
    assert any(event["action"] == "MERGE" for event in events)
    assert "Python" in facts[0]["fact_text"]
    assert "FastAPI" in facts[0]["fact_text"]


def test_pending_candidates_remain_pending_and_do_not_promote(temp_paths):
    db_path, mem_path = temp_paths
    PendingFactCandidateStore(db_path=db_path).add_candidate(
        PendingFactCandidateWrite(
            session_id="sess",
            fact="User may prefer compact plans",
            category="user_preference",
            confidence=0.7,
            explicit=False,
            source="secondary_llm_candidate",
        )
    )

    add_semantic_fact("user_pref", "User prefers FastAPI", db_path=db_path, memory_path=mem_path)

    pending = PendingFactCandidateStore(db_path=db_path).list_pending()
    assert len(pending) == 1
    assert pending[0].status == "PENDING"
    assert _count(db_path, "facts") == 1


def test_llm_candidates_still_never_write_to_permanent_facts(temp_paths, monkeypatch):
    db_path, mem_path = temp_paths
    from tests.test_phase7a_semantic_handler import FakeLLM, _job, _payload, _route
    from src.memory.job_handlers import SemanticCandidateExtractionJobHandler

    monkeypatch.setattr(
        "src.memory.job_handlers._resolve_secondary_route",
        lambda payload: _route(FakeLLM('{"candidates":[{"fact":"User prefers concise docs","category":"user_preference","confidence":0.8}]}')),
    )

    result = SemanticCandidateExtractionJobHandler().handle(
        job=_job(),
        payload=_payload(user_text="I prefer concise docs", assistant_text="OK"),
    )

    assert result.success is True
    assert _count(db_path, "pending_fact_candidates") == 1
    assert _count(db_path, "facts") == 0
    assert not mem_path.exists()
