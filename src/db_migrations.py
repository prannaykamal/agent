import sqlite3
import datetime
from pathlib import Path

def check_db_version(db_path: Path) -> int:
    """Returns current schema migration version."""
    if not db_path.exists():
        return 0
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(version) FROM schema_migrations")
        row = cursor.fetchone()
        conn.close()
        return row[0] if (row and row[0] is not None) else 0
    except Exception:
        return 0

def run_db_migrations(db_path: Path):

    """
    Applies versioned schema migrations to SQLite database.
    Ensures safe, idempotent database updates across restarts.
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Import and ensure base tables exist prior to index creation
    from src.db import _create_tables
    _create_tables(conn, db_path)

    # Create schema migrations table if missing
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            description TEXT NOT NULL,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()

    cursor.execute("SELECT MAX(version) FROM schema_migrations")
    row = cursor.fetchone()
    current_version = row[0] if (row and row[0] is not None) else 0

    migrations = [
        (1, "Initial schema: checkpoints, approval_requests"),
        (2, "Add Personal OS tables: tasks, scheduled_jobs, resource_locks, events_log, context_blocks"),
        (3, "Add loop_events step logger table"),
        (4, "Add real tool tables: calendar_events, emails, whatsapp_messages, telegram_messages"),
        (5, "Add session-based query indexes and formal tool_calls / tool_results tracking tables"),
        (6, "Add audit_logs table for medium/high risk operation security tracking"),
        (7, "Add idempotency_key and execution_status columns to approval_requests table"),
        (8, "Add memory runtime tables: memory_jobs, dead_letter_jobs, worker_heartbeats, summary_blocks"),
        (9, "Add durable cron scheduler tables"),
        (10, "Re-ensure memory runtime tables (formerly memory_entities backfill)"),
    ]

    for ver, desc in migrations:
        if ver > current_version:
            if ver == 1:
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_approval_status ON approval_requests(status);")
            elif ver == 2:
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);")
            elif ver == 3:
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_loop_events_session ON loop_events(session_id);")
            elif ver == 4:
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_calendar_start ON calendar_events(start_time);")
            elif ver == 5:
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_raw_turns_session ON raw_turns(session_id);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_loop_events_session_step ON loop_events(session_id, step_index);")
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS tool_calls (
                        id TEXT PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        tool_name TEXT NOT NULL,
                        tool_args TEXT,
                        status TEXT DEFAULT 'REQUESTED',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS tool_results (
                        id TEXT PRIMARY KEY,
                        tool_call_id TEXT NOT NULL,
                        session_id TEXT NOT NULL,
                        tool_name TEXT NOT NULL,
                        result_content TEXT,
                        status TEXT DEFAULT 'SUCCESS',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_tool_calls_session ON tool_calls(session_id);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_tool_results_session ON tool_results(session_id);")
            elif ver == 6:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS audit_logs (
                        id TEXT PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        tool_name TEXT NOT NULL,
                        tool_args_json TEXT,
                        risk_level TEXT NOT NULL,
                        action TEXT NOT NULL,
                        details TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_logs_session ON audit_logs(session_id);")
            elif ver == 7:
                try:
                    cursor.execute("ALTER TABLE approval_requests ADD COLUMN idempotency_key TEXT;")
                except sqlite3.OperationalError:
                    pass
                try:
                    cursor.execute("ALTER TABLE approval_requests ADD COLUMN execution_status TEXT DEFAULT 'PENDING';")
                except sqlite3.OperationalError:
                    pass
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_approval_idempotency ON approval_requests(idempotency_key);")
            elif ver == 8:
                from src.memory.schema import create_memory_schema
                create_memory_schema(conn)
            elif ver == 9:
                from src.personal_os.scheduler_store import create_scheduler_schema
                create_scheduler_schema(conn)
            elif ver == 10:
                # Formerly rebuilt the semantic entity index; long-term memory now lives in cognee.
                from src.memory.schema import create_memory_schema

                create_memory_schema(conn)

            cursor.execute(
                "INSERT INTO schema_migrations (version, description, applied_at) VALUES (?, ?, ?)",
                (ver, desc, datetime.datetime.now().isoformat())
            )
            conn.commit()

    conn.close()


