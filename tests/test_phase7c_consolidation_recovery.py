import json
from types import SimpleNamespace

import pytest

from src.db import init_db
from src.harness.llm_router import LLMRouteResult, LLMSelector
from src.memory.job_handlers import (
    SemanticCandidateExtractionJobHandler,
    SemanticConsolidationJobHandler,
)
from src.memory.semantic_candidates import PendingFactCandidateStore, PendingFactCandidateWrite
from src.memory.semantic_store import SemanticFactStore


@pytest.fixture
def temp_paths(tmp_path, monkeypatch):
    db_file = tmp_path / "phase7c_recovery.db"
    mem_file = tmp_path / "MEMORY.md"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    monkeypatch.setattr("src.config.MEMORY_PATH", mem_file)
    init_db(db_file)
    return db_file, mem_file


class FakeLLM:
    def __init__(self, content):
        self.content = content

    def invoke(self, prompt):
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


def _payload(candidate_ids):
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
            "window_key": "manual:sess:partial",
            "candidate_ids": candidate_ids,
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
            fact=f"Candidate fact {index}",
            category="general",
            confidence=0.7,
            explicit=False,
            source="secondary_llm_candidate",
            source_message_id=f"turn-{index}",
        )
    )


def test_candidate_specific_failure_marks_failed_without_clearing_batch(temp_paths, monkeypatch):
    db_path, _ = temp_paths
    store = PendingFactCandidateStore(db_path=db_path)
    failed = _candidate(store, 1)
    deferred = _candidate(store, 2)
    llm = FakeLLM(
        json.dumps(
            {
                "promote": [
                    {
                        "fact": "Candidate fact 1",
                        "category": "general",
                        "confidence": 0.8,
                        "source_candidate_ids": [failed.id],
                        "source_episode_ids": [],
                        "rationale": "test",
                    }
                ],
                "discard": [],
                "defer": [deferred.id],
            }
        )
    )
    monkeypatch.setattr("src.memory.job_handlers._resolve_secondary_route", lambda payload: _route(llm))

    def fail_add(self, *args, **kwargs):
        raise RuntimeError("dedup failure")

    monkeypatch.setattr(SemanticFactStore, "add_explicit_fact", fail_add)

    result = SemanticConsolidationJobHandler().handle(
        {"id": "job-consolidate-partial", "session_id": "sess"},
        _payload([failed.id, deferred.id]),
    )

    assert result.success is True
    assert result.result["run_status"] == "PARTIAL"
    assert store.get_by_id(failed.id).status == "FAILED"
    assert store.get_by_id(deferred.id).status == "DEFERRED"
    assert store.count_by_session("sess", status="PENDING") == 0


def test_semantic_candidate_extraction_remains_pending_only(temp_paths, monkeypatch):
    db_path, mem_path = temp_paths
    mem_path.write_text("original", encoding="utf-8")
    llm = FakeLLM(
        json.dumps(
            {
                "candidates": [
                    {
                        "fact": "User prefers consolidated memory",
                        "category": "user_preference",
                        "confidence": 0.7,
                        "rationale": "stated in chat",
                    }
                ]
            }
        )
    )
    monkeypatch.setattr("src.memory.job_handlers._resolve_secondary_route", lambda payload: _route(llm))

    result = SemanticCandidateExtractionJobHandler().handle(
        {"id": "job-semantic-candidates", "session_id": "sess"},
        {
            "schema_version": 1,
            "session_id": "sess",
            "models": {"secondary_provider": "openai", "secondary_model_name": "gpt-4o-mini"},
            "turn": {"user_text": "I prefer consolidated memory.", "assistant_text": "Noted."},
            "semantic": {"candidate_source": "post_turn"},
        },
    )

    assert result.success is True
    assert PendingFactCandidateStore(db_path=db_path).count_by_session("sess", status="PENDING") == 1
    assert mem_path.read_text(encoding="utf-8") == "original"
