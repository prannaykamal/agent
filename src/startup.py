from src.config import AGENT_DIR, SOUL_PATH, DB_PATH
from src.db import init_db

def ensure_system_initialized() -> dict:
    """
    Guarantees that all required directories, markdown memory files,
    and SQLite database schema tables are initialized cleanly on boot.
    """
    AGENT_DIR.mkdir(parents=True, exist_ok=True)
    scratch_dir = AGENT_DIR / "scratch"
    scratch_dir.mkdir(parents=True, exist_ok=True)

    # Initialize default SOUL.md if missing
    if not SOUL_PATH.exists():
        SOUL_PATH.write_text(
            "# System Prompt & Persona\n\n"
            "You are Ivo, an intelligent 24x7 personal assistant built on LangGraph, a cognee knowledge-graph memory, and MCP Gateway.\n"
            "Maintain strict safety policies, verify high-risk actions through Human-In-The-Loop approvals, and maintain accurate long-term memory.\n"
            "When tools are bound, call them instead of describing manual steps. For Gmail drafts, call email_draft with to, subject, and body.\n",
            encoding="utf-8"
        )

    # Long-term memory lives in cognee's own stores under .agent/cognee.
    (AGENT_DIR / "cognee").mkdir(parents=True, exist_ok=True)

    # Initialize SQLite Database
    init_db(DB_PATH)

    return {
        "status": "INITIALIZED",
        "agent_dir": str(AGENT_DIR),
        "db_path": str(DB_PATH),
        "soul_exists": SOUL_PATH.exists(),
        "cognee_dir": str(AGENT_DIR / "cognee"),
    }

