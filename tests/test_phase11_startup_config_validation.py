import sqlite3

import pytest
from fastapi.testclient import TestClient

from src.api.server import app
from src.db import init_db
from src.startup import ensure_system_initialized

client = TestClient(app)


@pytest.fixture
def temp_startup(tmp_path, monkeypatch):
    agent_dir = tmp_path / ".agent"
    db_file = agent_dir / "state.db"
    soul = agent_dir / "SOUL.md"
    memory = agent_dir / "MEMORY.md"
    skill = agent_dir / "SKILL.md"
    monkeypatch.setattr("src.config.AGENT_DIR", agent_dir)
    monkeypatch.setattr("src.config.DB_PATH", db_file)
    monkeypatch.setattr("src.config.SOUL_PATH", soul)
    monkeypatch.setattr("src.config.MEMORY_PATH", memory)
    monkeypatch.setattr("src.config.SKILL_PATH", skill)
    monkeypatch.setattr("src.startup.AGENT_DIR", agent_dir)
    monkeypatch.setattr("src.startup.DB_PATH", db_file)
    monkeypatch.setattr("src.startup.SOUL_PATH", soul)
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    return agent_dir, db_file, soul, memory, skill


def _tables(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    finally:
        conn.close()


def test_fresh_startup_creates_schema_cognee_dir_and_soul(temp_startup):
    agent_dir, db_file, soul, memory, skill = temp_startup

    result = ensure_system_initialized()

    assert result["status"] == "INITIALIZED"
    assert db_file.exists()
    assert soul.exists()
    assert (agent_dir / "cognee").is_dir()
    assert result["cognee_dir"] == str(agent_dir / "cognee")
    # Legacy memory mirrors and skill directories are no longer generated.
    assert not memory.exists()
    assert not skill.exists()
    assert not (agent_dir / "skills").exists()
    # Legacy tables still exist so old data can be imported into cognee.
    assert {"memory_jobs", "summary_blocks", "facts", "structured_episodes", "skill_versions"} <= _tables(db_file)


def test_startup_is_idempotent_and_preserves_existing_legacy_rows_and_skill_md(temp_startup):
    agent_dir, db_file, soul, memory, skill = temp_startup
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text("custom user compatibility index", encoding="utf-8")
    init_db(db_file)
    conn = sqlite3.connect(db_file)
    try:
        conn.execute("INSERT INTO facts (category, fact_text, source, confidence) VALUES ('profile', 'legacy row', 'test', 1.0)")
        conn.commit()
    finally:
        conn.close()

    first = ensure_system_initialized()
    second = ensure_system_initialized()

    conn = sqlite3.connect(db_file)
    try:
        fact_count = conn.execute("SELECT COUNT(*) FROM facts WHERE fact_text = 'legacy row'").fetchone()[0]
    finally:
        conn.close()
    assert first["status"] == second["status"] == "INITIALIZED"
    assert fact_count == 1
    assert skill.read_text(encoding="utf-8") == "custom user compatibility index"


def test_startup_does_not_start_memory_worker(temp_startup, monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("startup must not run worker jobs")

    monkeypatch.setattr("src.memory.worker.run_memory_worker_loop", fail)
    monkeypatch.setattr("src.memory.worker.process_one_memory_job", fail)

    ensure_system_initialized()


def test_missing_secondary_credentials_do_not_break_chat(temp_startup, monkeypatch):
    _, db_file, _, _, _ = temp_startup
    ensure_system_initialized()
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("XAI_API_KEY", raising=False)

    response = client.post(
        "/api/chat",
        json={"message": "Hello without secondary credentials", "session_id": "phase11-startup", "provider": "openai", "model_name": "gpt-4o-mini"},
    )

    assert response.status_code == 200
    assert "response" in response.json()


def test_environment_validation_exposes_mcp_booleans_not_secrets(monkeypatch):
    from src.config import validate_integration_environment

    monkeypatch.setenv("LEGACY_DIRECT_PROVIDER_SECRET", "hidden-value")

    result = validate_integration_environment()

    assert result["tavily"] is False
    assert result["telegram"] is False
    assert "hidden-value" not in str(result)
    assert "secret" not in str(result).lower()
