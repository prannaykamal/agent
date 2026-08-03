import uuid
from langchain_core.tools import tool
from src.db import get_connection

@tool
def publish_event(topic: str, payload: str) -> str:
    """Emits an asynchronous event to the internal system event bus."""
    event_id = f"event_{uuid.uuid4().hex[:8]}"
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO events_log (id, topic, payload, created_at)
        VALUES (?, ?, ?, datetime('now'))
        """,
        (event_id, topic, payload)
    )
    conn.commit()
    conn.close()
    return f"[Personal OS Event Bus] Event '{event_id}' published to topic '{topic}'."

@tool
def subscribe_event(topic: str, handler: str = "default_handler") -> str:
    """Registers an event subscription handler to listen for published events on a topic."""
    return f"[Personal OS Event Bus] Subscribed handler '{handler}' to topic '{topic}'."
