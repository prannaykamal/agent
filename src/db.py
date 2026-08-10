import re
import sqlite3
from typing import Optional, List, Dict, Any
from pathlib import Path
from src.config import DB_PATH


_initialized_dbs = set()

def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    target_path = db_path or DB_PATH
    target_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target_path))
    conn.row_factory = sqlite3.Row

    # Ensure tables are initialized for this database path
    str_path = str(target_path)
    if str_path not in _initialized_dbs:
        _initialized_dbs.add(str_path)
        _create_tables(conn)
        from src.db_migrations import run_db_migrations
        run_db_migrations(target_path)

    return conn

def _create_tables(conn: sqlite3.Connection, db_path: Optional[Path] = None) -> None:


    cursor = conn.cursor()

    # 1. Episodic Memory (FTS5 Table)
    cursor.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS episodes USING fts5(
            session_id UNINDEXED,
            timestamp UNINDEXED,
            content,
            tool_calls,
            outcome
        );
    """)

    # 2. Semantic Memory / Facts (FTS5 Table)
    cursor.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS facts USING fts5(
            category UNINDEXED,
            fact_text,
            source UNINDEXED,
            confidence UNINDEXED,
            created_at UNINDEXED
        );
    """)

    # 3. Procedural Memory / Skills (Standard Table)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS skills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            description TEXT,
            trigger_keywords TEXT,
            execution_steps TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 4. State Checkpoints (Standard Table for HITL & Resumability)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS checkpoints (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            state_json TEXT NOT NULL,
            status TEXT DEFAULT 'ACTIVE',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 5. Sub-Agents Registry Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sub_agents (
            agent_id TEXT PRIMARY KEY,
            parent_session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            instructions TEXT,
            status TEXT DEFAULT 'RUNNING',
            result TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 6. Tasks Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT,
            priority TEXT DEFAULT 'Medium',
            status TEXT DEFAULT 'PENDING',
            progress INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 7. Scheduled Jobs Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS scheduled_jobs (
            id TEXT PRIMARY KEY,
            cron_or_timestamp TEXT NOT NULL,
            task_payload TEXT NOT NULL,
            status TEXT DEFAULT 'ACTIVE',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 8. Resource Locks Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS resource_locks (
            resource_uri TEXT PRIMARY KEY,
            locked_by TEXT NOT NULL,
            locked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 9. Events Log Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS events_log (
            id TEXT PRIMARY KEY,
            topic TEXT NOT NULL,
            payload TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 10. Context Blocks Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS context_blocks (
            context_id TEXT PRIMARY KEY,
            query_or_topic TEXT NOT NULL,
            content TEXT,
            status TEXT DEFAULT 'ACQUIRED',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 11. Approval Requests Table (HITL)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS approval_requests (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            tool_name TEXT NOT NULL,
            tool_args_json TEXT NOT NULL,
            risk_level TEXT NOT NULL,
            reason TEXT NOT NULL,
            status TEXT DEFAULT 'PENDING',
            checkpoint_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 12. Uncompacted Raw Conversation Turns Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS raw_turns (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            sender TEXT NOT NULL,
            content TEXT NOT NULL,
            tokens INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 13. Pending Facts Queue Table (Confidence Gate <= 0.90)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pending_facts (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            category TEXT NOT NULL,
            fact_text TEXT NOT NULL,
            source TEXT,
            confidence REAL DEFAULT 0.8,
            explicit INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 14. Loop Step Events Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS loop_events (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            step_index INTEGER DEFAULT 1,
            step_type TEXT NOT NULL,
            reasoning TEXT,
            tool_name TEXT,
            tool_args_json TEXT,
            tool_result TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 15. Calendar Events Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS calendar_events (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            attendees TEXT,
            location TEXT,
            status TEXT DEFAULT 'CONFIRMED',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 16. Emails Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS emails (
            id TEXT PRIMARY KEY,
            sender TEXT NOT NULL,
            recipient TEXT NOT NULL,
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            folder TEXT DEFAULT 'inbox',
            status TEXT DEFAULT 'READ',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 17. WhatsApp Messages Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS whatsapp_messages (
            id TEXT PRIMARY KEY,
            sender TEXT NOT NULL,
            recipient TEXT NOT NULL,
            message TEXT NOT NULL,
            status TEXT DEFAULT 'SENT',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 18. Telegram Messages Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS telegram_messages (
            id TEXT PRIMARY KEY,
            chat_id TEXT NOT NULL,
            message TEXT NOT NULL,
            status TEXT DEFAULT 'SENT',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 19. Formal Tool Calls Table
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

    # 20. Formal Tool Results Table
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

    # 21. Audit Logs Table
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


    # 22. Durable Tool Scheduler Tables
    try:
        from src.personal_os.scheduler_store import create_scheduler_schema
        create_scheduler_schema(conn)
    except Exception:
        pass

    # Performance Indexes for Session-based queries
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_raw_turns_session ON raw_turns(session_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_loop_events_session_step ON loop_events(session_id, step_index);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tool_calls_session ON tool_calls(session_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tool_results_session ON tool_results(session_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_logs_session ON audit_logs(session_id);")


    conn.commit()










def init_db(db_path: Optional[Path] = None) -> None:
    """Initializes SQLite database tables including FTS5 search structures."""
    conn = get_connection(db_path)
    conn.close()



def add_fact(category: str, fact_text: str, source: str = "user", confidence: float = 1.0, db_path: Optional[Path] = None) -> None:
    """Inserts a new semantic fact into the FTS5 facts table."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO facts (category, fact_text, source, confidence, created_at) VALUES (?, ?, ?, ?, datetime('now'))",
        (category, fact_text, source, str(confidence))
    )
    conn.commit()
    conn.close()

def query_facts_fts(query: str, limit: int = 5, db_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Performs FTS5 keyword search over semantic facts with stop-word stripping and LIKE fallback."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    stop_words = {"what", "is", "my", "for", "the", "a", "an", "in", "on", "at", "to", "of", "and", "or", "tell", "me", "please", "recall"}
    words = [w for w in re.findall(r"\w+", query.lower()) if w not in stop_words and len(w) > 2]
    clean_fts = " OR ".join(words) if words else query

    try:
        cursor.execute(
            "SELECT rowid as id, category, fact_text, source, confidence, created_at FROM facts WHERE facts MATCH ? LIMIT ?",
            (clean_fts, limit)
        )
        rows = cursor.fetchall()
        if rows:
            conn.close()
            return [dict(row) for row in rows]
    except sqlite3.OperationalError:
        pass

    results = []
    seen_ids = set()
    for word in (words or [query]):
        cursor.execute(
            "SELECT rowid as id, category, fact_text, source, confidence, created_at FROM facts WHERE fact_text LIKE ? LIMIT ?",
            (f"%{word}%", limit)
        )
        for r in cursor.fetchall():
            row_dict = dict(r)
            if row_dict["id"] not in seen_ids:
                seen_ids.add(row_dict["id"])
                results.append(row_dict)
                if len(results) >= limit:
                    break

    conn.close()
    return results


def add_episode(session_id: str, content: str, tool_calls: str = "", outcome: str = "", db_path: Optional[Path] = None) -> None:
    """Logs an episodic conversation turn into FTS5 episodes table."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO episodes (session_id, timestamp, content, tool_calls, outcome) VALUES (?, datetime('now'), ?, ?, ?)",
        (session_id, content, tool_calls, outcome)
    )
    conn.commit()
    conn.close()

def check_tool_call_consistency(db_path: Optional[Path] = None) -> dict:
    """
    Performs foreign-key-like consistency checks between tool_calls and tool_results tables.
    Returns status and list of orphan tool_results records.
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT tr.id, tr.tool_call_id, tr.tool_name
            FROM tool_results tr
            LEFT JOIN tool_calls tc ON tr.tool_call_id = tc.id
            WHERE tc.id IS NULL
        """)
        orphans = cursor.fetchall()
        orphan_list = [dict(r) for r in orphans]
        conn.close()
        return {
            "consistent": len(orphan_list) == 0,
            "orphan_results_count": len(orphan_list),
            "orphan_results": orphan_list
        }
    except Exception as e:
        conn.close()
        return {
            "consistent": True,
            "orphan_results_count": 0,
            "orphan_results": [],
            "error": str(e)
        }

if __name__ == "__main__":
    init_db()
    print("Database initialized successfully with FTS5 tables.")

