import json
import sqlite3
from types import SimpleNamespace

import pytest

from src.db import init_db
from src.harness.llm_router import LLMRouteResult, LLMSelector
from src.memory.job_handlers import SemanticCandidateExtractionJobHandler, build_default_handler_registry


@pytest.fixture
def temp_paths(tmp_path, monkeypatch):
    db_file = tmp_path / "phase7a_handler.db"
    mem_file = tmp_path / "MEMORY.md"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    monkeypatch.setattr("src.config.MEMORY_PATH", mem_file)
    init_db(db_file)
    return db_file, mem_file


class FakeLLM:
    def __init__(self, text):
        self.text = text
        self.prompts = []

    def invoke(self, prompt):
        self.prompts.append(prompt)
        return SimpleNamespace(content=self.text)


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


def _payload(user_text="Remember that staging requires approval", assistant_text="Saved."):
    return {
        "schema_version": 1,
        "source": "graph.post_turn",
        "session_id": "sess",
        "turn": {
            "user_message_id": "user-1",
            "assistant_message_id": "assistant-1",
            "user_text": user_text,
            "assistant_text": assistant_text,
        },
        "models": {
            "primary_provider": "openai",
            "primary_model_name": "gpt-4o-mini",
            "secondary_provider": "openai",
            "secondary_model_name": "gpt-4o-mini",
        },
        "semantic": {"candidate_source": "post_turn"},
    }


def _job(job_id="job-semantic"):
    return {"id": job_id, "job_type": "semantic_candidate_extraction", "session_id": "sess"}


def _count(db_path, table):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def _pending_rows(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in conn.execute("SELECT * FROM pending_fact_candidates ORDER BY id").fetchall()]
    finally:
        conn.close()


def test_semantic_candidate_handler_registered_and_other_real_handlers_preserved():
    registry = build_default_handler_registry()

    assert isinstance(registry["semantic_candidate_extraction"], SemanticCandidateExtractionJobHandler)
    assert registry["summary_generation"].__class__.__name__ == "SummaryGenerationJobHandler"
    assert registry["episode_generation"].__class__.__name__ == "EpisodeGenerationJobHandler"
    assert registry["procedural_candidate_generation"].__class__.__name__ == "ProceduralCandidateGenerationJobHandler"
    assert registry["semantic_consolidation"].__class__.__name__ == "SemanticConsolidationJobHandler"
    assert registry["procedural_consolidation"].__class__.__name__ == "NoOpMemoryJobHandler"
    assert registry["skill_promotion"].__class__.__name__ == "SkillPromotionJobHandler"


def test_llm_candidates_write_only_pending_candidates(temp_paths, monkeypatch):
    db_path, mem_path = temp_paths
    mem_path.write_text("original", encoding="utf-8")
    fake_llm = FakeLLM(
        json.dumps(
            {
                "candidates": [
                    {
                        "fact": "User prefers implementation phases with test plans",
                        "category": "user_preference",
                        "confidence": 0.81,
                        "rationale": "The user requested phased roadmaps.",
                    }
                ]
            }
        )
    )
    monkeypatch.setattr("src.memory.job_handlers._resolve_secondary_route", lambda payload: _route(fake_llm))

    result = SemanticCandidateExtractionJobHandler().handle(
        job=_job(),
        payload=_payload(user_text="I prefer implementation phases with test plans", assistant_text="Understood."),
    )

    rows = _pending_rows(db_path)
    assert result.success is True
    assert result.result["llm_candidate_count"] == 1
    assert len(rows) == 1
    assert rows[0]["explicit"] == 0
    assert rows[0]["fact"] == "User prefers implementation phases with test plans"
    assert _count(db_path, "facts") == 0
    assert mem_path.read_text(encoding="utf-8") == "original"
    assert fake_llm.prompts


def test_durable_llm_candidates_are_promoted_to_permanent_facts(temp_paths, monkeypatch):
    db_path, mem_path = temp_paths
    fake_llm = FakeLLM(
        json.dumps(
            {
                "candidates": [
                    {
                        "fact": "You can reach Prannay at prannay@kamal.dev",
                        "category": "user_fact",
                        "confidence": 0.93,
                        "durable": True,
                        "rationale": "The user stated a lasting contact detail.",
                    },
                    {
                        "fact": "User asked to send five emails this turn",
                        "category": "user_fact",
                        "confidence": 0.99,
                        "durable": True,
                        "rationale": "Current task",
                    },
                    {
                        "fact": "User might like shorter answers",
                        "category": "user_preference",
                        "confidence": 0.4,
                        "durable": False,
                    },
                ]
            }
        )
    )
    monkeypatch.setattr("src.memory.job_handlers._resolve_secondary_route", lambda payload: _route(fake_llm))

    result = SemanticCandidateExtractionJobHandler().handle(
        job=_job(),
        payload=_payload(
            user_text="You can reach Prannay at prannay@kamal.dev. Send him five mails saying hi.",
            assistant_text="I will use that address.",
        ),
    )

    rows = _pending_rows(db_path)
    facts = [row[0] for row in __import__("sqlite3").connect(db_path).execute("SELECT fact_text FROM facts").fetchall()]
    assert result.success is True
    assert result.result["promoted_fact_count"] == 1
    assert any("prannay@kamal.dev" in fact for fact in facts)
    assert all("five emails" not in fact.lower() for fact in facts)
    promoted = [row for row in rows if row["status"] == "PROMOTED"]
    pending = [row for row in rows if row["status"] == "PENDING"]
    assert len(promoted) == 1
    assert len(pending) >= 1
    assert "prannay@kamal.dev" in mem_path.read_text(encoding="utf-8")
    assert "lasting contact" in fake_llm.prompts[0] or "durable" in fake_llm.prompts[0].lower()


def test_handler_writes_deterministic_explicit_candidates_and_is_idempotent(temp_paths, monkeypatch):
    db_path, _ = temp_paths
    monkeypatch.setattr("src.memory.job_handlers._resolve_secondary_route", lambda payload: _route(None, available=False))
    handler = SemanticCandidateExtractionJobHandler()

    first = handler.handle(job=_job(), payload=_payload())
    second = handler.handle(job=_job(), payload=_payload())

    assert first.success is True
    assert first.result["llm_available"] is False
    assert second.success is True
    assert _count(db_path, "pending_fact_candidates") == 1
    assert _count(db_path, "facts") == 0


def test_secondary_unavailable_without_deterministic_candidates_is_retryable(temp_paths, monkeypatch):
    db_path, _ = temp_paths
    monkeypatch.setattr("src.memory.job_handlers._resolve_secondary_route", lambda payload: _route(None, available=False))

    result = SemanticCandidateExtractionJobHandler().handle(
        job=_job(),
        payload=_payload(user_text="I prefer compact answers", assistant_text="OK"),
    )

    assert result.success is False
    assert result.retryable is True
    assert _count(db_path, "pending_fact_candidates") == 0


def test_invalid_llm_json_is_retryable_and_does_not_write_permanent_facts(temp_paths, monkeypatch):
    db_path, _ = temp_paths
    monkeypatch.setattr("src.memory.job_handlers._resolve_secondary_route", lambda payload: _route(FakeLLM("not json")))

    result = SemanticCandidateExtractionJobHandler().handle(
        job=_job(),
        payload=_payload(user_text="I prefer compact answers", assistant_text="OK"),
    )

    assert result.success is False
    assert result.retryable is True
    assert _count(db_path, "facts") == 0


def test_handler_parses_fenced_json_and_tolerates_minimal_payload(temp_paths, monkeypatch):
    db_path, _ = temp_paths
    monkeypatch.setattr(
        "src.memory.job_handlers._resolve_secondary_route",
        lambda payload: _route(FakeLLM('```json\n{"candidates":[{"fact":"User works in finance","category":"profile","confidence":0.7}]}\n```')),
    )

    result = SemanticCandidateExtractionJobHandler().handle(
        job=_job(),
        payload=_payload(user_text="I work in finance", assistant_text="Noted"),
    )
    minimal = SemanticCandidateExtractionJobHandler().handle(
        job=_job("job-minimal"),
        payload={"schema_version": 1},
    )

    assert result.success is True
    assert _count(db_path, "pending_fact_candidates") == 1
    assert minimal.success is True
    assert minimal.result["processed"] is False


