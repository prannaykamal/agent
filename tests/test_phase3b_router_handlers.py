import json
import sqlite3

import pytest

from src.db import init_db
from src.memory.job_handlers import ALL_MEMORY_JOB_TYPES, build_default_handler_registry
from src.memory.job_router import MemoryJobRouter


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "phase3b_router.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file


def _counts(db_path):
    tables = [
        "facts",
        "episodes",
        "pending_fact_candidates",
        "structured_episodes",
        "summary_blocks",
        "semantic_embeddings",
        "semantic_dedup_events",
        "consolidation_runs",
        "skill_candidates",
        "skill_versions",
        "skill_usage_stats",
    ]
    conn = sqlite3.connect(db_path)
    try:
        return {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables}
    finally:
        conn.close()


def test_every_memory_job_type_has_registered_handler_and_later_phase_jobs_are_noop():
    registry = build_default_handler_registry()

    assert set(registry) == set(ALL_MEMORY_JOB_TYPES)
    for job_type, handler in registry.items():
        if job_type == "summary_generation":
            assert handler.__class__.__name__ == "SummaryGenerationJobHandler"
            continue
        if job_type == "episode_generation":
            assert handler.__class__.__name__ == "EpisodeGenerationJobHandler"
            result = handler.handle(
                job={"id": f"job-{job_type}", "job_type": job_type},
                payload={"schema_version": 1},
            )
            assert result.success is False
            assert result.retryable is False
            assert result.result["processed"] is False
            continue
        if job_type == "semantic_consolidation":
            assert handler.__class__.__name__ == "SemanticConsolidationJobHandler"
            result = handler.handle(
                job={"id": f"job-{job_type}", "job_type": job_type},
                payload={"schema_version": 1},
            )
            assert result.success is False
            assert result.retryable is False
            assert result.result["processed"] is False
            continue
        result = handler.handle(
            job={"id": f"job-{job_type}", "job_type": job_type},
            payload={"schema_version": 1},
        )
        assert result.success is True
        assert result.result["processed"] is False
        assert result.result["job_type"] == job_type


def test_noop_handlers_do_not_call_llms(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("LLM should not be called")

    monkeypatch.setattr("src.harness.models.get_secondary_llm", fail)

    router = MemoryJobRouter()
    result = router.dispatch(
        {
            "id": "job-1",
            "job_type": "semantic_candidate_extraction",
            "payload_json": json.dumps({"schema_version": 1}),
        }
    )

    assert result.success is True
    assert result.result["processed"] is False


def test_noop_handlers_do_not_write_memory_tables(temp_db):
    before = _counts(temp_db)
    router = MemoryJobRouter()

    result = router.dispatch(
        {
            "id": "job-1",
            "job_type": "episode_generation",
            "payload_json": json.dumps({"schema_version": 1}),
        }
    )

    assert result.success is False
    assert result.retryable is False
    assert _counts(temp_db) == before


def test_unknown_job_type_returns_failure():
    router = MemoryJobRouter()

    result = router.dispatch(
        {
            "id": "job-unknown",
            "job_type": "unknown_job",
            "payload_json": json.dumps({"schema_version": 1}),
        }
    )

    assert result.success is False
    assert "Unknown memory job type" in result.result["message"]


def test_invalid_payload_returns_failure():
    router = MemoryJobRouter()

    result = router.dispatch(
        {
            "id": "job-invalid",
            "job_type": "semantic_candidate_extraction",
            "payload_json": "{not json",
        }
    )

    assert result.success is False
    assert result.result["message"] == "Invalid payload JSON"


def test_missing_schema_version_returns_failure():
    router = MemoryJobRouter()

    result = router.dispatch(
        {
            "id": "job-missing-schema",
            "job_type": "semantic_candidate_extraction",
            "payload_json": json.dumps({"source": "test"}),
        }
    )

    assert result.success is False
    assert "schema_version" in result.result["message"]




