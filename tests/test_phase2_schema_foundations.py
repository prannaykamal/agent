import sqlite3

import pytest

from src.db import get_connection, init_db
from src.db_migrations import check_db_version, run_db_migrations
from src.memory.schema import PHASE_X_MEMORY_TABLES


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
        assert set(PHASE_X_MEMORY_TABLES).issubset(_table_names(conn))
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
        assert set(PHASE_X_MEMORY_TABLES).issubset(_table_names(conn))
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
        assert set(PHASE_X_MEMORY_TABLES).issubset(_table_names(conn))
    finally:
        conn.close()


def test_legacy_memory_tables_remain_readable(temp_db):
    conn = get_connection(temp_db)
    try:
        conn.execute(
            "INSERT INTO facts (category, fact_text, source, confidence, created_at) VALUES (?, ?, ?, ?, datetime('now'))",
            ("preference", "User prefers concise reports.", "user", "1.0"),
        )
        conn.execute(
            "INSERT INTO episodes (session_id, timestamp, content, tool_calls, outcome) VALUES (?, datetime('now'), ?, '', '')",
            ("session-1", "User asked for Phase 2 schema foundations."),
        )
        conn.execute(
            "INSERT INTO raw_turns (id, session_id, sender, content, tokens) VALUES (?, ?, ?, ?, ?)",
            ("turn-1", "session-1", "user", "hello", 1),
        )
        conn.execute(
            """
            INSERT INTO pending_facts (id, session_id, category, fact_text, source, confidence, explicit)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("pf-1", "session-1", "preference", "likes additive migrations", "test", 0.8, 1),
        )
        conn.execute(
            "INSERT INTO skills (name, description, trigger_keywords, execution_steps) VALUES (?, ?, ?, ?)",
            ("legacy-skill", "legacy skill remains readable", "legacy", "do legacy thing"),
        )
        conn.commit()

        assert conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM raw_turns").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM pending_facts").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM skills").fetchone()[0] == 1
    finally:
        conn.close()


def test_key_columns_exist(temp_db):
    conn = sqlite3.connect(temp_db)
    try:
        memory_jobs = _columns(conn, "memory_jobs")
        assert {"id", "job_type", "status", "idempotency_key", "payload_json", "attempt_count", "max_attempts"}.issubset(memory_jobs)
        assert memory_jobs["payload_json"].upper() == "TEXT"

        structured_episodes = _columns(conn, "structured_episodes")
        assert {"id", "session_id", "title", "summary", "participants_json", "importance", "action"}.issubset(structured_episodes)
        assert structured_episodes["participants_json"].upper() == "TEXT"

        fact_candidates = _columns(conn, "pending_fact_candidates")
        assert {"id", "fact", "confidence", "explicit", "status", "metadata_json"}.issubset(fact_candidates)
        assert fact_candidates["metadata_json"].upper() == "TEXT"

        skill_versions = _columns(conn, "skill_versions")
        assert {"id", "skill_id", "version", "file_path", "content_hash", "frontmatter_json", "active"}.issubset(skill_versions)
        assert skill_versions["frontmatter_json"].upper() == "TEXT"
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
        assert {
            "idx_skill_versions_skill_version_unique",
            "idx_skill_versions_one_active_per_skill",
        }.issubset(_indexes(conn, "skill_versions"))
        assert "idx_semantic_embeddings_owner_model_unique" in _indexes(conn, "semantic_embeddings")
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
                """
                INSERT INTO structured_episodes (
                    id, session_id, title, summary, participants_json, goals_json,
                    decisions_json, artifacts_json, topics_json, importance,
                    start_message_id, end_message_id, source, action
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "episode-bad-importance",
                    "session-1",
                    "Title",
                    "Summary",
                    "[]",
                    "[]",
                    "[]",
                    "[]",
                    "[]",
                    1.5,
                    "m1",
                    "m2",
                    "test",
                    "CREATE",
                ),
            )

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO pending_fact_candidates (
                    id, session_id, fact, category, confidence, explicit, source, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("fact-bad-bool", "session-1", "fact", "preference", 0.5, 2, "test", "PENDING"),
            )

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO semantic_dedup_events (id, new_fact_text, action) VALUES (?, ?, ?)",
                ("dedup-bad-action", "fact", "IGNORE"),
            )

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO skill_versions (
                    id, skill_id, version, name, description, file_path, content_hash,
                    frontmatter_json, author, active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("sv-bad-version", "skill-1", 0, "Skill", "Desc", "skills/a.md", "hash", "{}", "test", 0),
            )

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO skill_usage_stats (skill_id, times_used) VALUES (?, ?)",
                ("skill-bad-usage", -1),
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


def test_duplicate_skill_id_version_fails(temp_db):
    conn = sqlite3.connect(temp_db)
    try:
        row = (
            "sv-1",
            "skill-1",
            1,
            "Skill",
            "Desc",
            "skills/a.md",
            "hash-a",
            "{}",
            "test",
        )
        conn.execute(
            """
            INSERT INTO skill_versions (
                id, skill_id, version, name, description, file_path, content_hash,
                frontmatter_json, author
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            row,
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO skill_versions (
                    id, skill_id, version, name, description, file_path, content_hash,
                    frontmatter_json, author
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("sv-2", "skill-1", 1, "Skill", "Desc", "skills/b.md", "hash-b", "{}", "test"),
            )
    finally:
        conn.close()
