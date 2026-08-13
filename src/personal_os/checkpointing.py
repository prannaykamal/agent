import json
import uuid
from langchain_core.tools import tool
from src.db import get_connection
from src.personal_os.audit import log_personal_os_action
from src.memory.short_term import get_raw_turns


@tool
def checkpoint(task_id: str) -> str:
    """Saves current execution state snapshot to SQLite table checkpoints for HITL pause & fault recovery."""
    checkpoint_id = f"chk_{uuid.uuid4().hex[:8]}"
    turns = []
    try:
        turns = get_raw_turns(session_id=task_id)[-20:]
    except Exception:
        turns = []
    state_payload = json.dumps({
        "task_id": task_id,
        "status": "CHECKPOINTED",
        "phase": "active",
        "recent_turns": [
            {"sender": item.get("sender"), "content": str(item.get("content") or "")[:2000]}
            for item in turns
            if isinstance(item, dict)
        ],
    })

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
    log_personal_os_action(
        tool_name="checkpoint",
        action="PERSONAL_OS_CHECKPOINT_CREATED",
        payload={"task_id": task_id},
        target_resource=checkpoint_id,
    )
    return f"[Personal OS Checkpoint] State snapshot saved with ID '{checkpoint_id}' for task '{task_id}'."


@tool
def restore_checkpoint(checkpoint_id: str) -> str:
    """Restores execution state snapshot from SQLite checkpoints table after a crash or HITL resume."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT session_id, state_json, status, created_at FROM checkpoints WHERE id = ?", (checkpoint_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return f"[Personal OS Checkpoint Error] Checkpoint '{checkpoint_id}' not found."

    cursor.execute("UPDATE checkpoints SET status = 'RESTORED' WHERE id = ?", (checkpoint_id,))
    conn.commit()
    conn.close()

    state_json = row["state_json"] if isinstance(row["state_json"], str) else json.dumps(row["state_json"])
    preview = state_json if len(state_json) <= 1500 else state_json[:1500] + "..."
    return (
        f"[Personal OS Checkpoint Restored] Restored state snapshot '{checkpoint_id}' "
        f"for session '{row['session_id']}' created at {row['created_at']}. State: {preview}"
    )
