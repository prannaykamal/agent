import sqlite3

import pytest

from src.db import get_connection, init_db
from src.db_migrations import check_db_version, run_db_migrations
from src.memory.schema import MEMORY_TABLES


def _table_names(conn):
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {row[0] for row in rows}


def _columns(conn, table_name):
    return {row[1]: row[2] for row in conn.execute(f"PRAGMA table_info({table_name})")}


def _indexes(conn, table_name):
    return {row[1] for row in conn.execute(f"PRAGMA index_list({table_name})")}


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "phase2_schema.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file


def test_empty_db_initialization_creates_phase2_tables(temp_db):
    conn = sqlite3.connect(temp_db)
    try:
        assert set(MEMORY_TABLES).issubset(_table_names(conn))
        assert check_db_version(temp_db) >= 8
    finally:
        conn.close()


def test_existing_db_migrates_to_version_8(tmp_path):
    db_file = tmp_path / "existing_v7.db"
    conn = sqlite3.connect(db_file)
    try:
        conn.execute(
            """
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                description TEXT NOT NULL,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            "INSERT INTO schema_migrations (version, description) VALUES (?, ?)",
            (7, "pre-existing schema"),
        )
        conn.commit()
    finally:
        conn.close()

    run_db_migrations(db_file)

    conn = sqlite3.connect(db_file)
    try:
        assert check_db_version(db_file) >= 8
        assert set(MEMORY_TABLES).issubset(_table_names(conn))
    finally:
        conn.close()


def test_phase2_migration_is_idempotent(temp_db):
    run_db_migrations(temp_db)
    run_db_migrations(temp_db)

    conn = sqlite3.connect(temp_db)
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version = 8"
        ).fetchone()[0]
        assert count == 1
        assert set(MEMORY_TABLES).issubset(_table_names(conn))
    finally:
        conn.close()


LEGACY_MEMORY_TABLES = {
    "episodes", "facts", "skills", "pending_facts",
    "structured_episodes", "pending_fact_candidates", "semantic_embeddings",
    "memory_entities", "semantic_dedup_events", "consolidation_runs",
    "skill_candidates", "skill_versions", "skill_usage_stats", "procedural_skill_approvals",
}


def test_fresh_db_does_not_create_legacy_memory_tables(temp_db):
    conn = sqlite3.connect(temp_db)
    try:
        assert LEGACY_MEMORY_TABLES.isdisjoint(_table_names(conn))
    finally:
        conn.close()


def test_existing_legacy_memory_rows_survive_migrations(tmp_path):
    db_file = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_file)
    try:
        conn.execute("CREATE VIRTUAL TABLE facts USING fts5(category UNINDEXED, fact_text, source UNINDEXED, confidence UNINDEXED, created_at UNINDEXED)")
        conn.execute("CREATE TABLE skills (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL, description TEXT, trigger_keywords TEXT, execution_steps TEXT)")
        conn.execute("INSERT INTO facts (category, fact_text, source, confidence, created_at) VALUES ('preference', 'User prefers concise reports.', 'user', '1.0', datetime('now'))")
        conn.execute("INSERT INTO skills (name, description, trigger_keywords, execution_steps) VALUES ('legacy-skill', 'desc', 'legacy', 'steps')")
        conn.commit()
    finally:
        conn.close()

    run_db_migrations(db_file)
    run_db_migrations(db_file)

    conn = sqlite3.connect(db_file)
    try:
        assert conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM skills").fetchone()[0] == 1
        assert set(MEMORY_TABLES).issubset(_table_names(conn))
    finally:
        conn.close()


def test_key_columns_exist(temp_db):
    conn = sqlite3.connect(temp_db)
    try:
        memory_jobs = _columns(conn, "memory_jobs")
        assert {"id", "job_type", "status", "idempotency_key", "payload_json", "attempt_count", "max_attempts"}.issubset(memory_jobs)
        assert memory_jobs["payload_json"].upper() == "TEXT"

        summary_blocks = _columns(conn, "summary_blocks")
        assert {"id", "session_id", "sequence_number", "summary", "covered_message_ids_json", "token_count"}.issubset(summary_blocks)
    finally:
        conn.close()


def test_key_indexes_exist(temp_db):
    conn = sqlite3.connect(temp_db)
    try:
        assert {
            "idx_memory_jobs_idempotency_key",
            "idx_memory_jobs_status_available_priority",
        }.issubset(_indexes(conn, "memory_jobs"))
        assert "idx_summary_blocks_session_sequence_unique" in _indexes(conn, "summary_blocks")
    finally:
        conn.close()


def test_invalid_check_constraints_fail(temp_db):
    conn = sqlite3.connect(temp_db)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO memory_jobs (id, job_type, status, idempotency_key) VALUES (?, ?, ?, ?)",
                ("job-bad-status", "summary", "INVALID", "idem-bad-status"),
            )

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO summary_blocks (id, session_id, sequence_number, summary, covered_message_ids_json, token_count) VALUES (?, ?, ?, ?, ?, ?)",
                ("sb-bad-seq", "session-1", 0, "summary", "[]", 1),
            )
    finally:
        conn.close()


def test_duplicate_memory_job_idempotency_key_fails(temp_db):
    conn = sqlite3.connect(temp_db)
    try:
        conn.execute(
            "INSERT INTO memory_jobs (id, job_type, idempotency_key) VALUES (?, ?, ?)",
            ("job-1", "summary", "idem-1"),
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO memory_jobs (id, job_type, idempotency_key) VALUES (?, ?, ?)",
                ("job-2", "summary", "idem-1"),
            )
    finally:
        conn.close()
