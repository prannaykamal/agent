import json
import sqlite3
from types import SimpleNamespace

import pytest

from src.db import init_db
from src.harness.llm_router import LLMRouteResult, LLMSelector
from src.memory.episode_store import StructuredEpisodeRepository
from src.memory.job_handlers import EpisodeGenerationJobHandler, build_default_handler_registry


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "phase6b_handler.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file


def _insert_turn(db_path, turn_id, sender, content, tokens=10):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO raw_turns (id, session_id, sender, content, tokens, created_at) VALUES (?, ?, ?, ?, ?, datetime('now'))",
            (turn_id, "sess", sender, content, tokens),
        )
        conn.commit()
    finally:
        conn.close()


def _payload(action="CREATE", parent=None):
    return {
        "schema_version": 1,
        "source": "graph.episode_detector",
        "session_id": "sess",
        "models": {
            "primary_provider": "openai",
            "primary_model_name": "gpt-4o-mini",
            "secondary_provider": "openai",
            "secondary_model_name": "gpt-4o-mini",
        },
        "trigger_metadata": {"explicit_memory_request": True},
        "episodic": {
            "schema_version": 1,
            "trigger_reason": "explicit_memory_request",
            "trigger_reasons": ["explicit_memory_request"],
            "source": "post_turn",
            "legacy_episode_backfill": False,
            "source_window": {
                "turn_ids": ["t1", "t2"],
                "start_message_id": "t1",
                "end_message_id": "t2",
                "token_count": 20,
                "source_text_mode": "raw_turns",
                "summary_block_ids": [],
                "user_text_hash": "u",
                "assistant_text_hash": "a",
            },
            "continuation": {
                "action": action,
                "parent_episode_id": parent,
                "related_episode_ids": [parent] if parent else [],
                "score": 0.8,
                "rationale_code": "test",
            },
        },
        "created_by": "phase_6b_episode_enqueue",
    }


def _job(job_id="job-episode"):
    return {"id": job_id, "job_type": "episode_generation", "session_id": "sess"}


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


def _episode_json(**overrides):
    data = {
        "title": "Deployment approval",
        "summary": "The user asked the assistant to remember deployment approval requirements.",
        "participants": ["User", "Assistant"],
        "goals": ["Preserve deployment rule"],
        "decisions": ["Require approval before deploy"],
        "artifacts": ["deploy.md"],
        "topics": ["Deployment", "Approval"],
        "importance": 0.9,
        "action": "MERGE",
        "parent_episode_id": "llm-parent",
    }
    data.update(overrides)
    return json.dumps(data)


def _count(db_path, table):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def test_registry_uses_real_episode_handler_and_preserves_other_handlers():
    registry = build_default_handler_registry()

    assert isinstance(registry["episode_generation"], EpisodeGenerationJobHandler)
    assert registry["summary_generation"].__class__.__name__ == "SummaryGenerationJobHandler"
    assert registry["semantic_candidate_extraction"].__class__.__name__ == "SemanticCandidateExtractionJobHandler"
    assert registry["procedural_candidate_generation"].__class__.__name__ == "ProceduralCandidateGenerationJobHandler"


def test_secondary_unavailable_returns_retryable_failure(temp_db, monkeypatch):
    _insert_turn(temp_db, "t1", "user", "Please remember deploy approval")
    _insert_turn(temp_db, "t2", "assistant", "OK")
    monkeypatch.setattr("src.memory.job_handlers._resolve_secondary_route", lambda payload: _route(None, available=False))

    result = EpisodeGenerationJobHandler().handle(job=_job(), payload=_payload())

    assert result.success is False
    assert result.retryable is True
    assert "Secondary LLM unavailable" in result.result["message"]
    assert _count(temp_db, "structured_episodes") == 0


def test_handler_parses_direct_json_and_appends_one_structured_episode(temp_db, monkeypatch):
    _insert_turn(temp_db, "t1", "user", "Please remember deploy approval")
    _insert_turn(temp_db, "t2", "assistant", "OK")
    fake_llm = FakeLLM(_episode_json())
    monkeypatch.setattr("src.memory.job_handlers._resolve_secondary_route", lambda payload: _route(fake_llm))

    result = EpisodeGenerationJobHandler().handle(job=_job(), payload=_payload(action="CREATE"))
    records = StructuredEpisodeRepository(db_path=temp_db).list_by_session("sess")

    assert result.success is True
    assert result.result["processed"] is True
    assert len(records) == 1
    assert records[0].title == "Deployment approval"
    assert records[0].action == "CREATE"
    assert records[0].parent_episode_id is None
    assert fake_llm.prompts
    assert "Return only JSON" in fake_llm.prompts[0]


def test_handler_parses_fenced_json(temp_db, monkeypatch):
    _insert_turn(temp_db, "t1", "user", "Please remember deploy approval")
    _insert_turn(temp_db, "t2", "assistant", "OK")
    monkeypatch.setattr(
        "src.memory.job_handlers._resolve_secondary_route",
        lambda payload: _route(FakeLLM("```json\n" + _episode_json(title="Fenced episode") + "\n```")),
    )

    result = EpisodeGenerationJobHandler().handle(job=_job(), payload=_payload())

    assert result.success is True
    assert StructuredEpisodeRepository(db_path=temp_db).list_by_session("sess")[0].title == "Fenced episode"


def test_handler_ignores_llm_supplied_action_and_uses_payload_action(temp_db, monkeypatch):
    _insert_turn(temp_db, "t1", "user", "Please remember deploy approval")
    _insert_turn(temp_db, "t2", "assistant", "OK")
    monkeypatch.setattr("src.memory.job_handlers._resolve_secondary_route", lambda payload: _route(FakeLLM(_episode_json(action="CREATE"))))

    EpisodeGenerationJobHandler().handle(job=_job(), payload=_payload(action="UPDATE", parent="episode-parent"))
    record = StructuredEpisodeRepository(db_path=temp_db).list_by_session("sess")[0]

    assert record.action == "UPDATE"
    assert record.parent_episode_id == "episode-parent"


def test_reprocessing_same_job_does_not_duplicate(temp_db, monkeypatch):
    _insert_turn(temp_db, "t1", "user", "Please remember deploy approval")
    _insert_turn(temp_db, "t2", "assistant", "OK")
    monkeypatch.setattr("src.memory.job_handlers._resolve_secondary_route", lambda payload: _route(FakeLLM(_episode_json())))
    handler = EpisodeGenerationJobHandler()

    first = handler.handle(job=_job(), payload=_payload())
    second = handler.handle(job=_job(), payload=_payload())

    assert first.success is True
    assert second.success is True
    assert second.result["processed"] is False
    assert _count(temp_db, "structured_episodes") == 1


def test_old_minimal_episode_payload_is_nonretryable_and_writes_nothing(temp_db):
    result = EpisodeGenerationJobHandler().handle(
        job=_job(),
        payload={"schema_version": 1, "episodic": {"trigger_reason": "explicit_memory_request"}},
    )

    assert result.success is False
    assert result.retryable is False
    assert _count(temp_db, "structured_episodes") == 0


def test_invalid_json_output_is_retryable(temp_db, monkeypatch):
    _insert_turn(temp_db, "t1", "user", "Please remember deploy approval")
    _insert_turn(temp_db, "t2", "assistant", "OK")
    monkeypatch.setattr("src.memory.job_handlers._resolve_secondary_route", lambda payload: _route(FakeLLM("not json")))

    result = EpisodeGenerationJobHandler().handle(job=_job(), payload=_payload())

    assert result.success is False
    assert result.retryable is True
    assert _count(temp_db, "structured_episodes") == 0


def test_handler_writes_no_legacy_or_unrelated_memory_tables(temp_db, monkeypatch):
    _insert_turn(temp_db, "t1", "user", "Please remember deploy approval")
    _insert_turn(temp_db, "t2", "assistant", "OK")
    monkeypatch.setattr("src.memory.job_handlers._resolve_secondary_route", lambda payload: _route(FakeLLM(_episode_json())))
    unrelated = [
        "episodes",
        "facts",
        "pending_fact_candidates",
        "summary_blocks",
        "semantic_embeddings",
        "semantic_dedup_events",
        "consolidation_runs",
        "skill_candidates",
        "skill_versions",
        "skill_usage_stats",
    ]
    before = {table: _count(temp_db, table) for table in unrelated}

    EpisodeGenerationJobHandler().handle(job=_job(), payload=_payload())

    assert {table: _count(temp_db, table) for table in unrelated} == before
    assert _count(temp_db, "structured_episodes") == 1



