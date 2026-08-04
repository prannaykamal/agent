import sqlite3

import pytest

from src.db import init_db
from src.memory.retrieval_sources import retrieve_summary_blocks
from src.memory.retrieval_types import RetrievalRequest
from src.memory.summary_blocks import SummaryBlockRepository


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "phase9a_summary.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file


def _append(repo, session_id, summary, job_id):
    return repo.append_summary_block(
        session_id=session_id,
        summary=summary,
        covered_message_ids=[f"{job_id}-turn-1", f"{job_id}-turn-2"],
        start_message_id=f"{job_id}-turn-1",
        end_message_id=f"{job_id}-turn-2",
        source_job_id=job_id,
        token_count=5,
        original_token_count=50,
        model_provider="openai",
        model_name="gpt-4o-mini",
    )


def _count(db_path, table):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def test_summary_retrieval_is_session_scoped_and_read_only(temp_db):
    repo = SummaryBlockRepository(db_path=temp_db)
    _append(repo, "session-a", "Discussed deployment budget and staging rollback.", "job-a")
    _append(repo, "session-b", "Discussed unrelated lunch plans.", "job-b")
    before_raw_turns = _count(temp_db, "raw_turns")
    before_summaries = _count(temp_db, "summary_blocks")

    result = retrieve_summary_blocks(
        RetrievalRequest(query="staging rollback", session_id="session-a", per_source_limit=5),
        db_path=temp_db,
    )

    assert result.source_name == "summary_blocks"
    assert [candidate.provenance.session_id for candidate in result.candidates] == ["session-a"]
    assert result.candidates[0].provenance.metadata["covered_message_ids"] == ["job-a-turn-1", "job-a-turn-2"]
    assert result.candidates[0].provenance.metadata["source_job_id"] == "job-a"
    assert _count(temp_db, "raw_turns") == before_raw_turns
    assert _count(temp_db, "summary_blocks") == before_summaries


def test_summary_retrieval_requires_session_id(temp_db):
    repo = SummaryBlockRepository(db_path=temp_db)
    _append(repo, "session-a", "Important summary", "job-a")

    result = retrieve_summary_blocks(RetrievalRequest(query="summary", session_id=None), db_path=temp_db)

    assert result.candidates == tuple()
