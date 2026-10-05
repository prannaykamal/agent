import json
import uuid
from typing import Any, Dict, Optional
from langchain_core.tools import tool
from src.db import get_connection
from src.personal_os.audit import log_personal_os_action
from src.memory.short_term import get_raw_turns


def save_checkpoint(task_id: str, extra_state: Optional[Dict[str, Any]] = None) -> str:
    """Persists a state snapshot to the checkpoints table and returns its ID.

    ``extra_state`` carries graph state that a HITL resume must restore (for
    example the turn's memory routing); it is stored alongside the recent turns.
    """
    checkpoint_id = f"chk_{uuid.uuid4().hex[:8]}"
    turns = []
    try:
        turns = get_raw_turns(session_id=task_id)[-20:]
    except Exception:
        turns = []
    state = {
        "task_id": task_id,
        "status": "CHECKPOINTED",
        "phase": "active",
        "recent_turns": [
            {"sender": item.get("sender"), "content": str(item.get("content") or "")[:2000]}
            for item in turns
            if isinstance(item, dict)
        ],
    }
    state.update(extra_state or {})

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO checkpoints (id, session_id, state_json, status, created_at)
        VALUES (?, ?, ?, 'ACTIVE', datetime('now'))
        """,
        (checkpoint_id, task_id, json.dumps(state, default=str))
    )
    conn.commit()
    conn.close()
    log_personal_os_action(
        tool_name="checkpoint",
        action="PERSONAL_OS_CHECKPOINT_CREATED",
        payload={"task_id": task_id},
        target_resource=checkpoint_id,
    )
    return checkpoint_id


def restore_checkpoint_state(checkpoint_id: str) -> Optional[Dict[str, Any]]:
    """Loads a checkpoint's state snapshot and marks it RESTORED. Returns None when missing."""
    if not checkpoint_id:
        return None
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT session_id, state_json, created_at FROM checkpoints WHERE id = ?", (checkpoint_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return None
    cursor.execute("UPDATE checkpoints SET status = 'RESTORED' WHERE id = ?", (checkpoint_id,))
    conn.commit()
    conn.close()

    try:
        state = json.loads(row["state_json"]) if isinstance(row["state_json"], str) else row["state_json"]
    except (TypeError, ValueError):
        state = None
    return {
        "session_id": row["session_id"],
        "created_at": row["created_at"],
        "state": state if isinstance(state, dict) else {},
    }


@tool
def checkpoint(task_id: str) -> str:
    """Saves current execution state snapshot to SQLite table checkpoints for HITL pause & fault recovery."""
    checkpoint_id = save_checkpoint(task_id)
    return f"[Personal OS Checkpoint] State snapshot saved with ID '{checkpoint_id}' for task '{task_id}'."


@tool
def restore_checkpoint(checkpoint_id: str) -> str:
    """Restores execution state snapshot from SQLite checkpoints table after a crash or HITL resume."""
    restored = restore_checkpoint_state(checkpoint_id)
    if restored is None:
        return f"[Personal OS Checkpoint Error] Checkpoint '{checkpoint_id}' not found."

    state_json = json.dumps(restored["state"])
    preview = state_json if len(state_json) <= 1500 else state_json[:1500] + "..."
    return (
        f"[Personal OS Checkpoint Restored] Restored state snapshot '{checkpoint_id}' "
        f"for session '{restored['session_id']}' created at {restored['created_at']}. State: {preview}"
    )
