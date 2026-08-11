import uuid
from langchain_core.tools import tool
from src.db import get_connection
from src.personal_os.audit import log_personal_os_action


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
    log_personal_os_action(
        tool_name="publish_event",
        action="PERSONAL_OS_EVENT_PUBLISHED",
        payload={"topic": topic, "payload": payload},
        target_resource=event_id,
    )
    return f"[Personal OS Event Bus] Event '{event_id}' published to topic '{topic}'."
