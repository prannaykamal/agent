import sqlite3
from langchain_core.tools import tool
from src.db import get_connection
from src.personal_os.audit import log_personal_os_action

@tool
def lock_resource(resource_uri: str) -> str:
    """Acquires a mutex lock on a shared resource to prevent race conditions across parallel agents."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO resource_locks (resource_uri, locked_by, locked_at)
            VALUES (?, 'agent_harness', datetime('now'))
            """,
            (resource_uri,)
        )
        conn.commit()
        log_personal_os_action(
            tool_name="lock_resource",
            action="PERSONAL_OS_RESOURCE_LOCKED",
            payload={"resource_uri": resource_uri},
            target_resource=resource_uri,
        )
        return f"[Personal OS Lock Acquired] Resource '{resource_uri}' locked successfully."
    except sqlite3.IntegrityError:
        cursor.execute("SELECT locked_by, locked_at FROM resource_locks WHERE resource_uri = ?", (resource_uri,))
        row = cursor.fetchone()
        return f"[Personal OS Lock Error] Resource '{resource_uri}' is currently locked by '{row['locked_by']}' since {row['locked_at']}."
    finally:
        conn.close()

@tool
def unlock_resource(resource_uri: str) -> str:
    """Releases a mutex lock on a shared resource."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM resource_locks WHERE resource_uri = ?", (resource_uri,))
    affected = cursor.rowcount
    conn.commit()
    conn.close()

    if affected == 0:
        return f"[Personal OS Lock Warning] Resource '{resource_uri}' was not locked."
    log_personal_os_action(
        tool_name="unlock_resource",
        action="PERSONAL_OS_RESOURCE_UNLOCKED",
        payload={"resource_uri": resource_uri},
        target_resource=resource_uri,
    )
    return f"[Personal OS Lock Released] Resource '{resource_uri}' unlocked successfully."
