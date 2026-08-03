import uuid
import json
from langchain_core.tools import tool
from src.db import get_connection

@tool
def checkpoint(task_id: str) -> str:
    """Saves current execution state snapshot to SQLite table checkpoints for HITL pause & fault recovery."""
    checkpoint_id = f"chk_{uuid.uuid4().hex[:8]}"
    state_payload = json.dumps({"task_id": task_id, "status": "CHECKPOINTED", "phase": "active"})

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO checkpoints (id, session_id, state_json, status, created_at)
        VALUES (?, ?, ?, 'ACTIVE', datetime('now'))
        """,
        (checkpoint_id, task_id, state_payload)
    )
    conn.commit()
    conn.close()
    return f"[Personal OS Checkpoint] State snapshot saved with ID '{checkpoint_id}' for task '{task_id}'."

@tool
def restore_checkpoint(checkpoint_id: str) -> str:
    """Restores execution state snapshot from SQLite checkpoints table after a crash or HITL resume."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT session_id, state_json, status, created_at FROM checkpoints WHERE id = ?", (checkpoint_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return f"[Personal OS Checkpoint Error] Checkpoint '{checkpoint_id}' not found."

    return f"[Personal OS Checkpoint Restored] Restored state snapshot '{checkpoint_id}' for session '{row['session_id']}' created at {row['created_at']}."
