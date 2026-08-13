from pathlib import Path
from typing import List, Dict, Any, Optional
from src.db import get_connection

def register_sub_agent(
    agent_id: str,
    parent_session_id: str,
    role: str,
    instructions: str,
    db_path: Optional[Path] = None
) -> None:
    """Registers a new sub-agent entry in SQLite database."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT OR REPLACE INTO sub_agents (agent_id, parent_session_id, role, instructions, status, created_at)
        VALUES (?, ?, ?, ?, 'RUNNING', datetime('now'))
        """,
        (agent_id, parent_session_id, role, instructions)
    )
    conn.commit()
    conn.close()

def update_sub_agent_status(
    agent_id: str,
    status: str,
    result: str = "",
    db_path: Optional[Path] = None
) -> None:
    """Updates status and result of a sub-agent."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE sub_agents
        SET status = ?, result = ?
        WHERE agent_id = ?
        """,
        (status, result, agent_id)
    )
    conn.commit()
    conn.close()

def get_sub_agent(
    agent_id: str,
    db_path: Optional[Path] = None
) -> Optional[Dict[str, Any]]:
    """Retrieves a sub-agent record by ID."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM sub_agents WHERE agent_id = ?", (agent_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def list_sub_agents(
    parent_session_id: Optional[str] = None,
    db_path: Optional[Path] = None
) -> List[Dict[str, Any]]:
    """Lists registered sub-agents, optionally filtered by parent session."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    if parent_session_id:
        cursor.execute("SELECT * FROM sub_agents WHERE parent_session_id = ? ORDER BY created_at DESC", (parent_session_id,))
    else:
        cursor.execute("SELECT * FROM sub_agents ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]
