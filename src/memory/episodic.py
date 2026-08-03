import json
import sqlite3
from pathlib import Path
from typing import List, Dict, Any, Optional
from src.db import get_connection, DB_PATH
from src.harness.models import get_secondary_llm

def should_trigger_episode(
    session_id: str,
    task_completed: bool = False,
    workflow_finished: bool = False,
    conversation_idle_seconds: float = 0,
    trimming_occurred: bool = False,
    conversation_tokens: int = 0
) -> bool:
    """
    Deterministic Episode Detector rules:
    - task_completed == True
    - workflow_finished == True
    - conversation_idle > 45 minutes (2700 seconds)
    - trimming_occurred == True
    - conversation_tokens > 50,000
    """
    if task_completed or workflow_finished or trimming_occurred:
        return True
    if conversation_idle_seconds >= 2700:  # 45 minutes
        return True
    if conversation_tokens >= 50000:
        return True
    return False

def generate_structured_episode_summary(
    session_id: str,
    history_text: str,
    provider: str = "openai"
) -> Dict[str, Any]:
    """
    Uses Secondary LLM to generate structured JSON episodic memory.
    """
    secondary_llm = get_secondary_llm(provider=provider)

    default_structure = {
        "title": f"Episode Session {session_id}",
        "summary": history_text[:200],
        "participants": ["User", "Assistant"],
        "goals": ["General Conversation"],
        "decisions": [],
        "artifacts": [],
        "topics": ["General"],
        "importance": 0.5
    }

    if not secondary_llm:
        return default_structure

    prompt = (
        f"Extract a structured JSON episodic memory summary from this conversation history:\n\n"
        f"{history_text}\n\n"
        f"Respond ONLY with a valid JSON object matching this exact schema:\n"
        f"{{\n"
        f'  "title": "Short descriptive title",\n'
        f'  "summary": "Concise summary of interaction",\n'
        f'  "participants": ["User", "Assistant"],\n'
        f'  "goals": ["List of main goals"],\n'
        f'  "decisions": ["Key decisions made"],\n'
        f'  "artifacts": ["Code files, links, or documents created"],\n'
        f'  "topics": ["Key topics discussed"],\n'
        f'  "importance": 0.85\n'
        f"}}\n"
    )

    try:
        resp = secondary_llm.invoke(prompt)
        content_str = str(resp.content).strip()
        # Strip markdown json backticks if present
        if content_str.startswith("```json"):
            content_str = content_str[7:-3].strip()
        elif content_str.startswith("```"):
            content_str = content_str[3:-3].strip()

        parsed = json.loads(content_str)
        if isinstance(parsed, dict) and "title" in parsed:
            return parsed
    except Exception as e:
        print(f"[Episodic Summary Warning] JSON parsing error: {e}")

    return default_structure

def create_structured_episode(
    session_id: str,
    structured_data: Dict[str, Any],
    db_path: Optional[Path] = None
) -> None:
    """Stores structured JSON episodic memory into SQLite FTS5 table."""
    conn = get_connection(db_path)
    cursor = conn.cursor()

    content_text = (
        f"Title: {structured_data.get('title', '')} | "
        f"Summary: {structured_data.get('summary', '')} | "
        f"Goals: {', '.join(structured_data.get('goals', []))} | "
        f"Decisions: {', '.join(structured_data.get('decisions', []))} | "
        f"Topics: {', '.join(structured_data.get('topics', []))}"
    )

    json_str = json.dumps(structured_data)

    cursor.execute(
        """
        INSERT INTO episodes (session_id, timestamp, content, tool_calls, outcome)
        VALUES (?, datetime('now'), ?, ?, ?)
        """,
        (session_id, content_text, json_str, "success")
    )
    conn.commit()
    conn.close()

def log_episode(
    session_id: str,
    content: str,
    tool_calls: str = "",
    outcome: str = "success",
    db_path: Optional[Path] = None
) -> None:
    """Logs a turn or task execution episode into SQLite FTS5 table."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO episodes (session_id, timestamp, content, tool_calls, outcome)
        VALUES (?, datetime('now'), ?, ?, ?)
        """,
        (session_id, content, tool_calls, outcome)
    )
    conn.commit()
    conn.close()

def search_episodes_fts(
    query: str,
    limit: int = 5,
    db_path: Optional[Path] = None
) -> List[Dict[str, Any]]:
    """Performs full-text search over episodic memory using SQLite FTS5."""
    if not query.strip():
        return []

    conn = get_connection(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT rowid as id, session_id, timestamp, content, tool_calls, outcome
            FROM episodes
            WHERE episodes MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (query, limit)
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    except sqlite3.OperationalError:
        cursor.execute(
            """
            SELECT rowid as id, session_id, timestamp, content, tool_calls, outcome
            FROM episodes
            WHERE content LIKE ?
            LIMIT ?
            """,
            (f"%{query}%", limit)
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()
