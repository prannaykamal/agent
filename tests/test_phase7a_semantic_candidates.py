import sqlite3

import pytest

from src.db import init_db
from src.memory.semantic_candidates import (
    PendingFactCandidateStore,
    PendingFactCandidateValidationError,
    PendingFactCandidateWrite,
    canonical_metadata_json,
)


@pytest.fixture
def temp_paths(tmp_path, monkeypatch):
    db_file = tmp_path / "phase7a_candidates.db"
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


def test_candidate_writes_to_pending_fact_candidates(temp_paths):
    db_path, _ = temp_paths
    store = PendingFactCandidateStore(db_path=db_path)

    record = store.add_candidate(
        PendingFactCandidateWrite(
            session_id="sess",
            fact="User prefers concise roadmaps",
            category="user_preference",
            confidence=0.82,
            explicit=False,
            source="secondary_llm_candidate",
            metadata={"b": 2, "a": 1},
        )
    )

    assert record.id.startswith("fact_candidate_")
    assert record.status == "PENDING"
    assert record.metadata == {"a": 1, "b": 2}
    assert store.count_by_session("sess") == 1
    assert _count(db_path, "facts") == 0


def test_candidate_writes_do_not_modify_memory_md(temp_paths):
    db_path, mem_path = temp_paths
    mem_path.write_text("original", encoding="utf-8")

    PendingFactCandidateStore(db_path=db_path).add_candidate(
        PendingFactCandidateWrite(
            session_id="sess",
            fact="User may prefer dark mode",
            category="user_preference",
            confidence=0.7,
            explicit=False,
            source="secondary_llm_candidate",
        )
    )

    assert mem_path.read_text(encoding="utf-8") == "original"


def test_deterministic_candidate_id_prevents_duplicates(temp_paths):
    db_path, _ = temp_paths
    store = PendingFactCandidateStore(db_path=db_path)
    write = PendingFactCandidateWrite(
        session_id="sess",
        fact="User prefers concise roadmaps",
        category="user_preference",
        confidence=0.82,
        explicit=False,
        source="secondary_llm_candidate",
        source_message_id="turn-1",
    )

    first = store.add_candidate(write)
    second = store.add_candidate(write)

    assert first.id == second.id
    assert store.count_by_session("sess") == 1


def test_candidate_validation_failures(temp_paths):
    db_path, _ = temp_paths

    with pytest.raises(PendingFactCandidateValidationError) as exc:
        PendingFactCandidateStore(db_path=db_path).add_candidate(
            PendingFactCandidateWrite(
                session_id="sess",
                fact="bad",
                category="general",
                confidence=2.0,
                explicit=False,
                source="secondary_llm_candidate",
            )
        )
    assert exc.value.field == "confidence"


def test_canonical_metadata_json_is_stable():
    assert canonical_metadata_json({"b": 2, "a": 1}) == '{"a":1,"b":2}'
