import sqlite3

import pytest

from src.db import init_db
from src.memory.semantic_dedup import (
    DeterministicSemanticDedupClassifier,
    SemanticDedupDecision,
    SemanticDedupInput,
    SemanticDedupService,
    SemanticDedupValidationError,
    validate_dedup_decision,
)
from src.memory.semantic_store import SemanticFactWrite


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "phase7b_dedup.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file


def _insert_fact(db_path, category, fact_text, confidence=0.9):
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(
            """
            INSERT INTO facts (category, fact_text, source, confidence, created_at)
            VALUES (?, ?, 'test_seed', ?, datetime('now'))
            """,
            (category, fact_text, str(confidence)),
        )
        conn.commit()
        return int(cursor.lastrowid)
    finally:
        conn.close()


def _input(text, category="user_pref"):
    return SemanticDedupInput(
        fact=SemanticFactWrite(category=category, fact_text=text, source="user_api", confidence=0.95)
    )


def test_no_existing_facts_returns_new(temp_db):
    decision = SemanticDedupService(db_path=temp_db).decide(_input("User prefers FastAPI"))

    assert decision.action == "NEW"


def test_exact_duplicate_returns_duplicate(temp_db):
    fact_id = _insert_fact(temp_db, "user_pref", "User prefers FastAPI")

    decision = SemanticDedupService(db_path=temp_db).decide(_input("User prefers FastAPI"))

    assert decision.action == "DUPLICATE"
    assert decision.target_fact_id == str(fact_id)


def test_near_duplicate_more_specific_incoming_returns_update(temp_db):
    fact_id = _insert_fact(temp_db, "user_pref", "User prefers Python")

    decision = SemanticDedupService(db_path=temp_db).decide(
        _input("User prefers Python for backend services")
    )

    assert decision.action == "UPDATE"
    assert decision.target_fact_id == str(fact_id)


def test_compatible_multi_fact_case_returns_merge(temp_db):
    first = _insert_fact(temp_db, "user_pref", "User prefers Python")
    second = _insert_fact(temp_db, "user_pref", "User prefers FastAPI")

    decision = SemanticDedupService(db_path=temp_db).decide(
        _input("User prefers Python and FastAPI for backend services")
    )

    assert decision.action == "MERGE"
    assert decision.target_fact_id in {str(first), str(second)}
    assert set(decision.merged_fact_ids) == ({str(first), str(second)} - {decision.target_fact_id})


def test_ambiguous_contradictory_case_returns_new(temp_db):
    _insert_fact(temp_db, "user_pref", "User prefers dark theme")

    decision = SemanticDedupService(db_path=temp_db).decide(_input("User prefers light theme"))

    assert decision.action == "NEW"


def test_invalid_dedup_action_rejected():
    with pytest.raises(SemanticDedupValidationError) as exc:
        validate_dedup_decision(
            SemanticDedupDecision(
                action="PROMOTE",  # type: ignore[arg-type]
                new_fact_text="User prefers FastAPI",
                category="user_pref",
                confidence=0.9,
            )
        )
    assert exc.value.field == "action"


def test_missing_target_for_duplicate_rejected():
    with pytest.raises(SemanticDedupValidationError) as exc:
        validate_dedup_decision(
            SemanticDedupDecision(
                action="DUPLICATE",
                new_fact_text="User prefers FastAPI",
                category="user_pref",
                confidence=0.9,
            )
        )
    assert exc.value.field == "target_fact_id"


def test_classifier_does_not_call_llms(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("LLM should not be called")

    monkeypatch.setattr("src.harness.models.get_model_instance", fail)

    decision = DeterministicSemanticDedupClassifier().classify(_input("User prefers FastAPI"), [])

    assert decision.action == "NEW"
