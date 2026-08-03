import json
import sqlite3

import pytest

from src.db import init_db
from src.memory.summary_blocks import SummaryBlockRepository


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "phase5b_summary_repo.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file


def test_append_and_list_summary_blocks_with_canonical_coverage(temp_db):
    repo = SummaryBlockRepository(db_path=temp_db)

    block = repo.append_summary_block(
        session_id="sess",
        summary="Important context.",
        covered_message_ids=["turn_b", "turn_a"],
        start_message_id="turn_b",
        end_message_id="turn_a",
        source_job_id="job-1",
        token_count=4,
        original_token_count=40,
        model_provider="openai",
        model_name="gpt-4o-mini",
    )

    rows = repo.list_summary_blocks("sess")
    conn = sqlite3.connect(temp_db)
    try:
        encoded = conn.execute(
            "SELECT covered_message_ids_json FROM summary_blocks WHERE id = ?",
            (block.id,),
        ).fetchone()[0]
    finally:
        conn.close()

    assert rows == [block]
    assert json.loads(encoded) == ["turn_b", "turn_a"]
    assert encoded == '["turn_b","turn_a"]'


def test_sequence_numbers_increment_per_session(temp_db):
    repo = SummaryBlockRepository(db_path=temp_db)

    first = repo.append_summary_block(
        session_id="sess-a",
        summary="One",
        covered_message_ids=["a1"],
        start_message_id="a1",
        end_message_id="a1",
        source_job_id="job-a1",
        token_count=1,
        original_token_count=10,
        model_provider="openai",
        model_name="gpt-4o-mini",
    )
    second = repo.append_summary_block(
        session_id="sess-a",
        summary="Two",
        covered_message_ids=["a2"],
        start_message_id="a2",
        end_message_id="a2",
        source_job_id="job-a2",
        token_count=1,
        original_token_count=10,
        model_provider="openai",
        model_name="gpt-4o-mini",
    )
    other = repo.append_summary_block(
        session_id="sess-b",
        summary="Other",
        covered_message_ids=["b1"],
        start_message_id="b1",
        end_message_id="b1",
        source_job_id="job-b1",
        token_count=1,
        original_token_count=10,
        model_provider="openai",
        model_name="gpt-4o-mini",
    )

    assert first.sequence_number == 1
    assert second.sequence_number == 2
    assert other.sequence_number == 1


def test_covered_ids_and_source_job_lookup(temp_db):
    repo = SummaryBlockRepository(db_path=temp_db)
    block = repo.append_summary_block(
        session_id="sess",
        summary="Coverage",
        covered_message_ids=["turn_1", "turn_2"],
        start_message_id="turn_1",
        end_message_id="turn_2",
        source_job_id="job-source",
        token_count=2,
        original_token_count=20,
        model_provider="openai",
        model_name="gpt-4o-mini",
    )

    assert repo.get_covered_message_ids("sess") == {"turn_1", "turn_2"}
    assert repo.get_by_source_job_id("job-source") == block


def test_append_rejects_empty_summary_and_empty_coverage(temp_db):
    repo = SummaryBlockRepository(db_path=temp_db)

    with pytest.raises(ValueError):
        repo.append_summary_block(
            session_id="sess",
            summary="",
            covered_message_ids=["turn_1"],
            start_message_id="turn_1",
            end_message_id="turn_1",
            source_job_id="job-1",
            token_count=0,
            original_token_count=0,
            model_provider="openai",
            model_name="gpt-4o-mini",
        )

    with pytest.raises(ValueError):
        repo.append_summary_block(
            session_id="sess",
            summary="Non-empty",
            covered_message_ids=[],
            start_message_id=None,
            end_message_id=None,
            source_job_id="job-2",
            token_count=1,
            original_token_count=1,
            model_provider="openai",
            model_name="gpt-4o-mini",
        )


def test_repository_exposes_no_update_or_delete_api():
    repo = SummaryBlockRepository()

    assert not hasattr(repo, "update_summary_block")
    assert not hasattr(repo, "delete_summary_block")
