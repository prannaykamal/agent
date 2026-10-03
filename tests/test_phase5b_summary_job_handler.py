import json
import sqlite3
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage

from src.db import init_db
from src.harness.llm_router import LLMRouteResult, LLMSelector
from src.memory.job_handlers import SummaryGenerationJobHandler, build_default_handler_registry
from src.memory.summary_blocks import SummaryBlockRepository


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "phase5b_handler.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file


def _insert_turn(db_path, turn_id, sender, content, tokens=10, session_id="sess"):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO raw_turns (id, session_id, sender, content, tokens, created_at) VALUES (?, ?, ?, ?, ?, datetime('now'))",
            (turn_id, session_id, sender, content, tokens),
        )
        conn.commit()
    finally:
        conn.close()


def _payload():
    return {
        "schema_version": 1,
        "source": "graph.short_term_budget",
        "session_id": "sess",
        "models": {
            "primary_provider": "openai",
            "primary_model_name": "gpt-4o",
            "secondary_provider": "openai",
            "secondary_model_name": "gpt-4o-mini",
        },
        "summary_generation": {
            "reason": "token_budget_exceeded",
            "chunk_ratio": 0.30,
            "context_window": 128000,
            "conversation_budget_tokens": 96000,
            "summarization_trigger_tokens": 86400,
            "historical_conversation_tokens": 90000,
            "selected_turn_ids": ["t1", "t2"],
            "start_message_id": "t1",
            "end_message_id": "t2",
            "selected_token_count": 20,
            "eligible_token_count": 90,
        },
        "created_by": "phase_5b_summary_enqueue",
    }


def _job():
    return {"id": "job-summary", "job_type": "summary_generation", "session_id": "sess"}


class FakeLLM:
    def __init__(self, text="summary text"):
        self.text = text
        self.prompts = []

    def invoke(self, prompt):
        self.prompts.append(prompt)
        return AIMessage(content=self.text)


def _route(llm=None, available=True):
    return LLMRouteResult(
        selector=LLMSelector(
            role="secondary",
            provider="openai",
            model_name="gpt-4o-mini",
            temperature=0.3,
            context_window=128000,
            source="test",
        ),
        llm=llm,
        available=available,
        fallback_used=False,
        error=None if available else "unavailable",
    )


def _count(db_path, table):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def test_default_registry_uses_real_summary_and_cognee_handlers():
    registry = build_default_handler_registry()

    assert isinstance(registry["summary_generation"], SummaryGenerationJobHandler)
    assert registry["cognee_ingest"].__class__.__name__ == "CogneeIngestJobHandler"
    assert registry["memory_session_write"].__class__.__name__ == "MemorySessionWriteJobHandler"
    assert registry["memory_session_merge"].__class__.__name__ == "MemorySessionMergeJobHandler"


def test_summary_handler_appends_exactly_one_block(temp_db, monkeypatch):
    _insert_turn(temp_db, "t1", "user", "Please remember the deadline.")
    _insert_turn(temp_db, "t2", "assistant", "The deadline is Friday.")
    fake_llm = FakeLLM("Deadline is Friday.")
    monkeypatch.setattr("src.memory.job_handlers._resolve_secondary_route", lambda payload: _route(fake_llm))

    result = SummaryGenerationJobHandler().handle(job=_job(), payload=_payload())
    blocks = SummaryBlockRepository(db_path=temp_db).list_summary_blocks("sess")

    assert result.success is True
    assert result.result["processed"] is True
    assert len(blocks) == 1
    assert blocks[0].summary == "Deadline is Friday."
    assert blocks[0].covered_message_ids == ["t1", "t2"]
    assert fake_llm.prompts


def test_reprocessing_same_job_does_not_duplicate_block(temp_db, monkeypatch):
    _insert_turn(temp_db, "t1", "user", "A")
    _insert_turn(temp_db, "t2", "assistant", "B")
    monkeypatch.setattr("src.memory.job_handlers._resolve_secondary_route", lambda payload: _route(FakeLLM()))
    handler = SummaryGenerationJobHandler()

    first = handler.handle(job=_job(), payload=_payload())
    second = handler.handle(job=_job(), payload=_payload())

    assert first.success is True
    assert second.success is True
    assert second.result["processed"] is False
    assert _count(temp_db, "summary_blocks") == 1


def test_secondary_unavailable_returns_retryable_failure(temp_db, monkeypatch):
    _insert_turn(temp_db, "t1", "user", "A")
    _insert_turn(temp_db, "t2", "assistant", "B")
    monkeypatch.setattr("src.memory.job_handlers._resolve_secondary_route", lambda payload: _route(None, available=False))

    result = SummaryGenerationJobHandler().handle(job=_job(), payload=_payload())

    assert result.success is False
    assert result.retryable is True
    assert "Secondary LLM unavailable" in result.result["message"]
    assert _count(temp_db, "summary_blocks") == 0


def test_invalid_payload_returns_nonretryable_failure():
    result = SummaryGenerationJobHandler().handle(
        job=_job(),
        payload={"schema_version": 1, "summary_generation": {"selected_turn_ids": []}},
    )

    assert result.success is False
    assert result.retryable is False


def test_summary_handler_does_not_write_unrelated_memory_tables(temp_db, monkeypatch):
    _insert_turn(temp_db, "t1", "user", "A")
    _insert_turn(temp_db, "t2", "assistant", "B")
    monkeypatch.setattr("src.memory.job_handlers._resolve_secondary_route", lambda payload: _route(FakeLLM()))
    unrelated = [
        "facts",
        "episodes",
        "pending_fact_candidates",
        "structured_episodes",
        "semantic_embeddings",
        "semantic_dedup_events",
        "consolidation_runs",
        "skill_candidates",
        "skill_versions",
        "skill_usage_stats",
    ]
    before = {table: _count(temp_db, table) for table in unrelated}

    SummaryGenerationJobHandler().handle(job=_job(), payload=_payload())

    assert {table: _count(temp_db, table) for table in unrelated} == before
    assert _count(temp_db, "summary_blocks") == 1


