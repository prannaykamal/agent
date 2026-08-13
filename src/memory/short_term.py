import uuid
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional
from langchain_core.messages import BaseMessage
from src.db import get_connection

def estimate_tokens(messages: List[BaseMessage]) -> int:
    """Estimates total token count of a message list using character heuristic (~4 chars/token)."""
    total_chars = sum(len(str(m.content)) for m in messages)
    return total_chars // 4

def log_raw_turn(
    session_id: str,
    sender: str,
    content: str,
    db_path: Optional[Path] = None
) -> str:
    """Logs an uncompacted raw conversation turn to SQLite table raw_turns."""
    turn_id = f"turn_{uuid.uuid4().hex[:8]}"
    tokens = len(content) // 4
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO raw_turns (id, session_id, sender, content, tokens, created_at)
        VALUES (?, ?, ?, ?, ?, datetime('now'))
        """,
        (turn_id, session_id, sender, content, tokens)
    )
    conn.commit()
    conn.close()
    return turn_id

def get_raw_turns(
    session_id: str,
    db_path: Optional[Path] = None
) -> List[Dict[str, Any]]:
    """Retrieves all complete uncompacted conversation turns for a session_id."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT id, session_id, sender, content, tokens, created_at FROM raw_turns WHERE session_id = ? ORDER BY created_at ASC", (session_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_compaction_ratio(context_window_limit: int) -> float:
    """
    Returns model capacity-based compaction ratio:
    - 1M+ context models (Gemini) -> 0.20 (summarize oldest 20%)
    - 400k context models -> 0.25 (summarize oldest 25%)
    - 128k/200k context models (OpenAI/Anthropic/Grok) -> 0.30 (summarize oldest 30%)
    """
    if context_window_limit >= 1000000:
        return 0.20
    elif context_window_limit >= 400000:
        return 0.25
    return 0.30

def manage_short_term_memory_with_budget(
    messages: List[BaseMessage],
    existing_summary: str = "",
    context_window_limit: int = 128000,
    provider: str = "openai"
) -> Tuple[List[BaseMessage], str]:
    """Compatibility wrapper retained after Phase 5B.

    Runtime short-term context management now uses immutable summary blocks and
    async summary_generation jobs. This function intentionally performs no
    synchronous summarization, no trimming, and no secondary LLM calls.
    """
    return messages, existing_summary


def manage_short_term_memory(
    messages: List[BaseMessage],
    existing_summary: str = "",
    max_messages: Optional[int] = None,
    **kwargs
) -> Tuple[List[BaseMessage], str]:
    """Compatibility wrapper retained after Phase 5B without message-count trimming."""
    return messages, existing_summary

def generate_thread_title(
    user_message: str,
    secondary_provider: Optional[str] = None,
    secondary_model_name: Optional[str] = None
) -> str:
    """Generates a concise deterministic topic title without LLM calls."""
    clean_msg = user_message.strip()
    if not clean_msg:
        return "New Chat"

    words = [w for w in clean_msg.split() if w.strip()]
    if not words:
        return "New Chat"
    title_words = words[:5]
    raw_title = " ".join(title_words)
    return raw_title[0].upper() + raw_title[1:] if raw_title else "New Chat"
