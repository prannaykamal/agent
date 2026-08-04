import inspect
import json
import sqlite3
from types import SimpleNamespace

import pytest

from src.db import init_db
from src.harness.llm_router import LLMRouteResult, LLMSelector
from src.memory.job_handlers import (
    SemanticConsolidationJobHandler,
    SemanticCandidateExtractionJobHandler,
    build_default_handler_registry,
)
from src.memory.semantic_candidates import PendingFactCandidateStore, PendingFactCandidateWrite
from src.memory.semantic_consolidation import SemanticConsolidationService


@pytest.fixture
def temp_paths(tmp_path, monkeypatch):
    db_file = tmp_path / "phase7c_handler.db"
    mem_file = tmp_path / "MEMORY.md"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    monkeypatch.setattr("src.config.MEMORY_PATH", mem_file)
    init_db(db_file)
    return db_file, mem_file


class FakeLLM:
    def __init__(self, content):
        self.content = content
        self.calls = []

    def invoke(self, prompt):
        self.calls.append(prompt)
        return SimpleNamespace(content=self.content)


def _route(llm):
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
        available=llm is not None,
        fallback_used=False,
    )


def _payload(candidate_ids=None):
    return {
        "schema_version": 1,
        "source": "test",
        "session_id": "sess",
        "models": {
            "primary_provider": "openai",
            "primary_model_name": "gpt-4o-mini",
            "secondary_provider": "openai",
            "secondary_model_name": "gpt-4o-mini",
        },
        "semantic_consolidation": {
            "schema_version": 1,
            "trigger_type": "manual",
            "window_key": "manual:sess:test",
            "candidate_ids": candidate_ids or [],
            "episode_ids": [],
            "candidate_batch_size": 100,
            "recent_episode_limit": 10,
            "current_memory_limit": 50,
        },
    }


def _candidate(store, index):
    return store.add_candidate(
        PendingFactCandidateWrite(
            session_id="sess",
            fact=f"User prefers test fact {index}",
            category="user_preference",
            confidence=0.78,
            explicit=False,
            source="secondary_llm_candidate",
            source_message_id=f"turn-{index}",
        )
    )


def _count(db_path, table):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def test_semantic_consolidation_handler_registered_and_other_handlers_preserved():
    registry = build_default_handler_registry()

    assert isinstance(registry["semantic_consolidation"], SemanticConsolidationJobHandler)
    assert isinstance(registry["semantic_candidate_extraction"], SemanticCandidateExtractionJobHandler)
    assert registry["summary_generation"].__class__.__name__ == "SummaryGenerationJobHandler"
    assert registry["episode_generation"].__class__.__name__ == "EpisodeGenerationJobHandler"
    assert registry["procedural_consolidation"].__class__.__name__ == "NoOpMemoryJobHandler"
    assert registry["skill_promotion"].__class__.__name__ == "SkillPromotionJobHandler"


def test_secondary_unavailable_returns_candidates_to_pending(temp_paths, monkeypatch):
    db_path, _ = temp_paths
    store = PendingFactCandidateStore(db_path=db_path)
    candidate = _candidate(store, 1)
    monkeypatch.setattr("src.memory.job_handlers._resolve_secondary_route", lambda payload: _route(None))

    result = SemanticConsolidationJobHandler().handle(
        {"id": "job-consolidate-1", "session_id": "sess"},
        _payload([candidate.id]),
    )

    assert result.success is False
    assert result.retryable is True
    assert store.get_by_id(candidate.id).status == "PENDING"
    assert _count(db_path, "facts") == 0


def test_invalid_json_recovers_claimed_candidates(temp_paths, monkeypatch):
    db_path, _ = temp_paths
    store = PendingFactCandidateStore(db_path=db_path)
    candidate = _candidate(store, 1)
    monkeypatch.setattr("src.memory.job_handlers._resolve_secondary_route", lambda payload: _route(FakeLLM("not-json")))

    result = SemanticConsolidationJobHandler().handle(
        {"id": "job-consolidate-2", "session_id": "sess"},
        _payload([candidate.id]),
    )

    assert result.success is False
    assert store.get_by_id(candidate.id).status == "PENDING"
    assert _count(db_path, "facts") == 0


def test_valid_llm_output_promotes_through_semantic_fact_store(temp_paths, monkeypatch):
    db_path, mem_path = temp_paths
    store = PendingFactCandidateStore(db_path=db_path)
    promote = _candidate(store, 1)
    discard = _candidate(store, 2)
    defer = _candidate(store, 3)
    unreferenced = _candidate(store, 4)
    llm = FakeLLM(
        json.dumps(
            {
                "promote": [
                    {
                        "fact": "User prefers test fact 1",
                        "category": "user_preference",
                        "confidence": 0.86,
                        "source_candidate_ids": [promote.id],
                        "source_episode_ids": [],
                        "rationale": "Stable user preference",
                    }
                ],
                "discard": [discard.id],
                "defer": [defer.id],
            }
        )
    )
    monkeypatch.setattr("src.memory.job_handlers._resolve_secondary_route", lambda payload: _route(llm))

    result = SemanticConsolidationJobHandler().handle(
        {"id": "job-consolidate-3", "session_id": "sess"},
        _payload([promote.id, discard.id, defer.id, unreferenced.id]),
    )

    assert result.success is True
    assert result.result["fact_count"] == 1
    assert store.get_by_id(promote.id).status == "PROMOTED"
    assert store.get_by_id(discard.id).status == "DISCARDED"
    assert store.get_by_id(defer.id).status == "DEFERRED"
    assert store.get_by_id(unreferenced.id).status == "DEFERRED"
    assert _count(db_path, "facts") == 1
    assert _count(db_path, "semantic_embeddings") == 1
    assert _count(db_path, "semantic_dedup_events") == 1
    assert _count(db_path, "consolidation_runs") == 1
    assert "User prefers test fact 1" in mem_path.read_text(encoding="utf-8")


def test_handler_uses_dedup_store_and_does_not_directly_insert_facts():
    handler_source = inspect.getsource(SemanticConsolidationJobHandler.handle)
    service_source = inspect.getsource(SemanticConsolidationService.apply_output)

    assert "_insert_fact" not in handler_source
    assert "INSERT INTO facts" not in handler_source
    assert "add_explicit_fact" in service_source
