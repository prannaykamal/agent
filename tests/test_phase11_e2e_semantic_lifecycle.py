import json
import sqlite3
from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage

from src.db import add_fact, init_db
from src.harness.graph import node_retrieval_gate
from src.harness.llm_router import LLMRouteResult, LLMSelector
from src.memory.job_handlers import SemanticCandidateExtractionJobHandler, SemanticConsolidationJobHandler
from src.memory.semantic import add_semantic_fact
from src.memory.semantic_candidates import PendingFactCandidateStore, PendingFactCandidateWrite
from src.memory.semantic_store import SemanticFactRecord


@pytest.fixture
def temp_paths(tmp_path, monkeypatch):
    db_file = tmp_path / "phase11_semantic.db"
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


def _route(llm=None, available=True):
    return LLMRouteResult(
        selector=LLMSelector("secondary", "openai", "gpt-4o-mini", 0.3, 128000, "test"),
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


def _semantic_payload(user_text="I prefer compact architecture docs", assistant_text="Noted"):
    return {
        "schema_version": 1,
        "session_id": "phase11-semantic",
        "turn": {"user_text": user_text, "assistant_text": assistant_text},
        "models": {"secondary_provider": "openai", "secondary_model_name": "gpt-4o-mini"},
        "semantic": {"candidate_source": "post_turn"},
    }


def _consolidation_payload(candidate_ids):
    return {
        "schema_version": 1,
        "session_id": "phase11-semantic",
        "models": {"secondary_provider": "openai", "secondary_model_name": "gpt-4o-mini"},
        "semantic_consolidation": {
            "schema_version": 1,
            "trigger_type": "manual",
            "window_key": "manual:phase11-semantic",
            "candidate_ids": candidate_ids,
            "episode_ids": [],
            "candidate_batch_size": 100,
            "recent_episode_limit": 10,
            "current_memory_limit": 50,
        },
    }


def test_explicit_fact_write_uses_semantic_fact_store(temp_paths, monkeypatch):
    calls = []

    def fake_add(self, fact, **kwargs):
        calls.append((fact, kwargs))
        return SemanticFactRecord(1, fact.category, fact.fact_text, fact.source, fact.confidence, "now")

    monkeypatch.setattr("src.memory.semantic_store.SemanticFactStore.add_explicit_fact", fake_add)

    add_semantic_fact("profile", "User prefers deterministic tests", source="phase11")

    assert len(calls) == 1
    assert calls[0][0].fact_text == "User prefers deterministic tests"


def test_semantic_extraction_writes_pending_candidates_only(temp_paths, monkeypatch):
    db_path, mem_path = temp_paths
    mem_path.write_text("original", encoding="utf-8")
    llm = FakeLLM(json.dumps({"candidates": [{"fact": "User prefers stable releases", "category": "preference", "confidence": 0.82}]}))
    monkeypatch.setattr("src.memory.job_handlers._resolve_secondary_route", lambda payload: _route(llm))

    result = SemanticCandidateExtractionJobHandler().handle(
        {"id": "semantic-job", "job_type": "semantic_candidate_extraction", "session_id": "phase11-semantic"},
        _semantic_payload("I prefer stable releases", "Noted"),
    )

    assert result.success is True
    assert _count(db_path, "pending_fact_candidates") == 1
    assert _count(db_path, "facts") == 0
    assert mem_path.read_text(encoding="utf-8") == "original"


def test_consolidation_promotes_through_dedup_store_and_records_events(temp_paths, monkeypatch):
    db_path, mem_path = temp_paths
    candidate = PendingFactCandidateStore(db_path=db_path).add_candidate(
        PendingFactCandidateWrite(
            session_id="phase11-semantic",
            fact="User prefers stable releases",
            category="preference",
            confidence=0.85,
            explicit=False,
            source="secondary_llm_candidate",
        )
    )
    llm = FakeLLM(
        json.dumps(
            {
                "promote": [
                    {
                        "fact": "User prefers stable releases",
                        "category": "preference",
                        "confidence": 0.9,
                        "source_candidate_ids": [candidate.id],
                        "source_episode_ids": [],
                        "rationale": "Stable preference",
                    }
                ],
                "discard": [],
                "defer": [],
            }
        )
    )
    monkeypatch.setattr("src.memory.job_handlers._resolve_secondary_route", lambda payload: _route(llm))

    result = SemanticConsolidationJobHandler().handle(
        {"id": "semantic-consolidation-job", "job_type": "semantic_consolidation", "session_id": "phase11-semantic"},
        _consolidation_payload([candidate.id]),
    )

    assert result.success is True
    assert _count(db_path, "facts") == 1
    assert _count(db_path, "semantic_embeddings") == 1
    assert _count(db_path, "semantic_dedup_events") == 1
    assert PendingFactCandidateStore(db_path=db_path).get_by_id(candidate.id).status == "PROMOTED"
    assert "User prefers stable releases" in mem_path.read_text(encoding="utf-8")


def test_consolidation_failure_returns_claimed_candidates_to_pending(temp_paths, monkeypatch):
    db_path, _ = temp_paths
    store = PendingFactCandidateStore(db_path=db_path)
    candidate = store.add_candidate(
        PendingFactCandidateWrite(
            session_id="phase11-semantic",
            fact="User prefers recoverable failures",
            category="preference",
            confidence=0.8,
            explicit=False,
            source="secondary_llm_candidate",
        )
    )
    monkeypatch.setattr("src.memory.job_handlers._resolve_secondary_route", lambda payload: _route(FakeLLM("not json")))

    result = SemanticConsolidationJobHandler().handle(
        {"id": "semantic-consolidation-fail", "job_type": "semantic_consolidation", "session_id": "phase11-semantic"},
        _consolidation_payload([candidate.id]),
    )

    assert result.success is False
    assert result.retryable is True
    assert store.get_by_id(candidate.id).status == "PENDING"
    assert _count(db_path, "facts") == 0


def test_semantic_retrieval_does_not_write_embeddings_or_dedup_events(temp_paths, monkeypatch):
    db_path, _ = temp_paths
    add_fact("profile", "User prefers read only retrieval", db_path=db_path)
    before = {table: _count(db_path, table) for table in ["semantic_embeddings", "semantic_dedup_events"]}

    def fail_upsert(*args, **kwargs):
        raise AssertionError("retrieval must not upsert embeddings")

    monkeypatch.setattr("src.memory.embeddings.SemanticEmbeddingStore.upsert_embedding", fail_upsert)
    result = node_retrieval_gate({"messages": [HumanMessage(content="what read only retrieval preference do I have?")], "session_id": "phase11-semantic"})

    after = {table: _count(db_path, table) for table in before}
    assert result["retrieval_triggered"] is True
    assert after == before
