import sqlite3

import pytest

from src.db import init_db
from src.memory.summary_blocks import (
    SummaryBlockRepository,
    get_adaptive_summary_chunk_ratio,
    select_oldest_summary_chunk,
)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "phase5b_chunk.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file


def _insert_turn(db_path, turn_id, sender, content, tokens, session_id="sess"):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO raw_turns (id, session_id, sender, content, tokens, created_at) VALUES (?, ?, ?, ?, ?, datetime('now'))",
            (turn_id, session_id, sender, content, tokens),
        )
        conn.commit()
    finally:
        conn.close()


def test_adaptive_chunk_ratio_thresholds():
    assert get_adaptive_summary_chunk_ratio(128000) == 0.30
    assert get_adaptive_summary_chunk_ratio(200000) == 0.30
    assert get_adaptive_summary_chunk_ratio(300000) == 0.25
    assert get_adaptive_summary_chunk_ratio(500000) == 0.25
    assert get_adaptive_summary_chunk_ratio(500001) == 0.20
    assert get_adaptive_summary_chunk_ratio(1000000) == 0.20


def test_selects_oldest_chunk_by_token_mass_not_message_count(temp_db):
    _insert_turn(temp_db, "t1", "user", "old small 1", 5)
    _insert_turn(temp_db, "t2", "assistant", "old small 2", 5)
    _insert_turn(temp_db, "t3", "user", "old large", 90)
    _insert_turn(temp_db, "t4", "assistant", "recent", 1)
    _insert_turn(temp_db, "t5", "user", "current", 1)
    repo = SummaryBlockRepository(db_path=temp_db)

    selection = select_oldest_summary_chunk(
        session_id="sess",
        context_window=128000,
        repository=repo,
        current_user_turn_id="t5",
    )

    assert selection is not None
    assert selection.eligible_token_count == 101
    assert selection.chunk_ratio == 0.30
    assert selection.selected_turn_ids == ["t1", "t2", "t3"]
    assert selection.selected_token_count == 100


def test_already_summarized_turns_are_excluded(temp_db):
    _insert_turn(temp_db, "t1", "user", "covered", 50)
    _insert_turn(temp_db, "t2", "assistant", "eligible", 50)
    _insert_turn(temp_db, "t3", "user", "current", 10)
    repo = SummaryBlockRepository(db_path=temp_db)
    repo.append_summary_block(
        session_id="sess",
        summary="Covered t1",
        covered_message_ids=["t1"],
        start_message_id="t1",
        end_message_id="t1",
        source_job_id="job-1",
        token_count=3,
        original_token_count=50,
        model_provider="openai",
        model_name="gpt-4o-mini",
    )

    selection = select_oldest_summary_chunk(
        session_id="sess",
        context_window=128000,
        repository=repo,
        current_user_turn_id="t3",
    )

    assert selection is not None
    assert selection.selected_turn_ids == ["t2"]


def test_latest_user_turn_is_excluded_by_default(temp_db):
    _insert_turn(temp_db, "t1", "user", "old", 40)
    _insert_turn(temp_db, "t2", "assistant", "answer", 40)
    _insert_turn(temp_db, "t3", "user", "current", 100)
    repo = SummaryBlockRepository(db_path=temp_db)

    selection = select_oldest_summary_chunk(
        session_id="sess",
        context_window=128000,
        repository=repo,
    )

    assert selection is not None
    assert "t3" not in selection.selected_turn_ids


def test_no_eligible_turns_returns_none(temp_db):
    _insert_turn(temp_db, "t1", "user", "current", 10)
    repo = SummaryBlockRepository(db_path=temp_db)

    assert select_oldest_summary_chunk(
        session_id="sess",
        context_window=128000,
        repository=repo,
    ) is None
