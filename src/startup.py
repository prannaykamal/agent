from pathlib import Path
from src.config import AGENT_DIR, MEMORY_PATH, SOUL_PATH, SKILL_PATH, DB_PATH
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
            "You are an intelligent 24x7 Personal Assistant built on LangGraph, SQLite FTS5 RAG, and MCP Gateway.\n"
            "Maintain strict safety policies, verify high-risk actions through Human-In-The-Loop approvals, and maintain accurate long-term memory.\n",
            encoding="utf-8"
        )

    # Initialize default MEMORY.md if missing
    if not MEMORY_PATH.exists():
        MEMORY_PATH.write_text(
            "# Key Facts & Long-Term Memory\n\n"
            "## Verified Facts\n"
            "- Assistant active with multi-provider LLM support.\n",
            encoding="utf-8"
        )

    # Initialize default SKILL.md if missing
    if not SKILL_PATH.exists():
        SKILL_PATH.write_text(
            "# Procedural Skills & Workflows\n\n"
            "## Skills Catalog\n"
            "- **general_assistant**: Answers questions and manages tasks cleanly.\n",
            encoding="utf-8"
        )

    # Initialize SQLite Database
    init_db(DB_PATH)

    return {
        "status": "INITIALIZED",
        "agent_dir": str(AGENT_DIR),
        "db_path": str(DB_PATH),
        "soul_exists": SOUL_PATH.exists(),
        "memory_exists": MEMORY_PATH.exists(),
        "skill_exists": SKILL_PATH.exists()
    }
