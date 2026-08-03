from pathlib import Path
from typing import Optional
from langchain_core.messages import SystemMessage
from src.config import SOUL_PATH

def load_soul_prompt(path: Optional[Path] = None) -> SystemMessage:
    """Loads the SOUL.md system prompt file and wraps it in a LangChain SystemMessage."""
    target_path = path or SOUL_PATH
    if not target_path.exists():
        default_content = (
            "You are Antigravity, a 24x7 Personal AI Assistant. "
            "Operate professionally, maintain privacy, and adhere strictly to safety rules."
        )
        return SystemMessage(content=default_content)

    content = target_path.read_text(encoding="utf-8").strip()
    return SystemMessage(content=content)
