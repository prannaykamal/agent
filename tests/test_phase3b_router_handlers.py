import json
import sqlite3

import pytest

from src.db import init_db
from src.memory.job_handlers import ALL_MEMORY_JOB_TYPES, NoOpMemoryJobHandler, build_default_handler_registry
from src.memory.job_router import MemoryJobRouter


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "phase3b_router.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file


def _counts(db_path):
    tables = [
        "memory_jobs",
        "summary_blocks",
    ]
    conn = sqlite3.connect(db_path)
    try:
        return {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables}
    finally:
        conn.close()


def test_every_memory_job_type_has_a_real_handler():
    registry = build_default_handler_registry()

    assert set(registry) == set(ALL_MEMORY_JOB_TYPES) == {"summary_generation", "cognee_ingest", "memory_session_write", "memory_session_merge"}
    assert registry["summary_generation"].__class__.__name__ == "SummaryGenerationJobHandler"
    assert registry["cognee_ingest"].__class__.__name__ == "CogneeIngestJobHandler"
    assert registry["memory_session_write"].__class__.__name__ == "MemorySessionWriteJobHandler"
    assert registry["memory_session_merge"].__class__.__name__ == "MemorySessionMergeJobHandler"


def test_noop_handler_succeeds_without_processing():
    handler = NoOpMemoryJobHandler(job_type="future_job")

    result = handler.handle(job={"id": "job-1"}, payload={"schema_version": 1})

    assert result.success is True
    assert result.result["processed"] is False
    assert result.result["job_type"] == "future_job"


def test_cognee_jobs_without_cognee_do_not_call_llms_or_write_tables(temp_db, monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("LLM should not be called")

    monkeypatch.setattr("src.harness.models.get_secondary_llm", fail)
    before = _counts(temp_db)
    router = MemoryJobRouter()

    ingest = router.dispatch(
        {
            "id": "job-1",
            "job_type": "cognee_ingest",
            "payload_json": json.dumps({"schema_version": 1, "documents": ["fact"]}),
        }
    )
    write = router.dispatch(
        {
            "id": "job-2",
            "job_type": "memory_session_write",
            "payload_json": json.dumps({"schema_version": 1, "session_id": "s1", "text": "fact"}),
        }
    )

    assert (ingest.success, ingest.retryable) == (False, False)
    assert (write.success, write.retryable) == (False, False)
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
            "job_type": "cognee_ingest",
            "payload_json": "{not json",
        }
    )

    assert result.success is False
    assert result.result["message"] == "Invalid payload JSON"


def test_missing_schema_version_returns_failure():
    result = NoOpMemoryJobHandler(job_type="future_job").handle(job={"id": "job-missing-schema"}, payload={"source": "test"})

    assert result.success is False
    assert "schema_version" in result.result["message"]
