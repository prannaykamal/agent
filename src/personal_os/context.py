import uuid
from langchain_core.tools import tool
from src.db import get_connection

@tool
def acquire_context(query_or_topic: str) -> str:
    """Loads a specific context block into active working memory context."""
    context_id = f"ctx_{uuid.uuid4().hex[:8]}"
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO context_blocks (context_id, query_or_topic, content, status, created_at)
        VALUES (?, ?, ?, 'ACQUIRED', datetime('now'))
        """,
        (context_id, query_or_topic, f"Loaded context block for topic '{query_or_topic}'")
    )
    conn.commit()
    conn.close()
    return f"[Personal OS Context Acquired] Context block ID '{context_id}' loaded for topic '{query_or_topic}'."

@tool
def release_context(context_id: str) -> str:
    """Frees an active context block from working memory to conserve context budget."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE context_blocks SET status = 'RELEASED' WHERE context_id = ?", (context_id,))
    affected = cursor.rowcount
    conn.commit()
    conn.close()

    if affected == 0:
        return f"[Personal OS Context Warning] Context ID '{context_id}' not found."
    return f"[Personal OS Context Released] Context block '{context_id}' released from working memory."
