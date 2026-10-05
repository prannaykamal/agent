"""SQLite schema for the memory runtime: the durable job queue, worker
heartbeats, and short-term summary blocks.

Long-term memory lives in cognee, not SQLite. The pre-cognee episodic,
semantic, and procedural tables are no longer created; existing databases keep
their rows for ``src.memory.cognee_backfill``.
"""

from sqlite3 import Connection


MEMORY_TABLES = [
    "memory_jobs",
    "dead_letter_jobs",
    "worker_heartbeats",
    "summary_blocks",
]


def create_memory_schema(conn: Connection) -> None:
    """Create the memory runtime tables idempotently."""
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS memory_jobs (
            id TEXT PRIMARY KEY,
            job_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'QUEUED'
                CHECK (status IN ('QUEUED','RUNNING','RETRYING','SUCCEEDED','FAILED','DEAD_LETTERED','CANCELLED')),
            priority INTEGER NOT NULL DEFAULT 100 CHECK (priority >= 0),
            session_id TEXT,
            idempotency_key TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            result_json TEXT,
            error_message TEXT,
            attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
            max_attempts INTEGER NOT NULL DEFAULT 3 CHECK (max_attempts > 0),
            available_at TEXT NOT NULL DEFAULT (datetime('now')),
            locked_by TEXT,
            locked_at TEXT,
            started_at TEXT,
            completed_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_jobs_idempotency_key ON memory_jobs(idempotency_key);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_memory_jobs_status_available_priority ON memory_jobs(status, available_at, priority, created_at);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_memory_jobs_session ON memory_jobs(session_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_memory_jobs_type_status ON memory_jobs(job_type, status);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_memory_jobs_locked_by ON memory_jobs(locked_by);")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS dead_letter_jobs (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            job_type TEXT NOT NULL,
            session_id TEXT,
            idempotency_key TEXT,
            payload_json TEXT NOT NULL DEFAULT '{}',
            last_error TEXT NOT NULL,
            error_details_json TEXT,
            attempt_count INTEGER NOT NULL CHECK (attempt_count > 0),
            failed_at TEXT NOT NULL DEFAULT (datetime('now')),
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_dead_letter_jobs_job_id ON dead_letter_jobs(job_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_dead_letter_jobs_type_failed ON dead_letter_jobs(job_type, failed_at);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_dead_letter_jobs_session ON dead_letter_jobs(session_id);")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS worker_heartbeats (
            worker_id TEXT PRIMARY KEY,
            worker_type TEXT NOT NULL,
            status TEXT NOT NULL
                CHECK (status IN ('STARTING','RUNNING','IDLE','STOPPING','STOPPED','ERROR','STALE')),
            current_job_id TEXT,
            last_heartbeat_at TEXT NOT NULL DEFAULT (datetime('now')),
            started_at TEXT NOT NULL DEFAULT (datetime('now')),
            metadata_json TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_worker_heartbeats_type_status ON worker_heartbeats(worker_type, status);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_worker_heartbeats_last_seen ON worker_heartbeats(last_heartbeat_at);")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS summary_blocks (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            sequence_number INTEGER NOT NULL CHECK (sequence_number > 0),
            summary TEXT NOT NULL,
            covered_message_ids_json TEXT NOT NULL,
            start_message_id TEXT,
            end_message_id TEXT,
            source_job_id TEXT,
            token_count INTEGER NOT NULL CHECK (token_count >= 0),
            original_token_count INTEGER CHECK (original_token_count IS NULL OR original_token_count >= 0),
            model_provider TEXT,
            model_name TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_summary_blocks_session_sequence_unique ON summary_blocks(session_id, sequence_number);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_summary_blocks_session_created ON summary_blocks(session_id, created_at);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_summary_blocks_source_job ON summary_blocks(source_job_id);")

    conn.commit()
