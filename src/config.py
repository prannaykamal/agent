import os
from pathlib import Path
from dotenv import load_dotenv
from src.memory.config import load_memory_config

load_dotenv()

# Base paths
BASE_DIR = Path(__file__).resolve().parent.parent
AGENT_DIR = BASE_DIR / ".agent"
AGENT_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = AGENT_DIR / "state.db"
SOUL_PATH = AGENT_DIR / "SOUL.md"
MEMORY_PATH = AGENT_DIR / "MEMORY.md"
SKILL_PATH = AGENT_DIR / "SKILL.md"

# LLM Configurations
PRIMARY_MODEL = os.getenv("PRIMARY_MODEL", "gpt-4o-mini")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")

# Short-term memory limits
MAX_MESSAGES_BEFORE_TRIM = int(os.getenv("MAX_MESSAGES_BEFORE_TRIM", "10"))
TOKEN_TRIM_THRESHOLD = int(os.getenv("TOKEN_TRIM_THRESHOLD", "4000"))

# Phase X typed memory architecture config loader. Legacy constants above remain
# available for compatibility until their subsystems are migrated.
def get_memory_config():
    return load_memory_config()

# LangSmith Tracing Setup
def setup_langsmith_tracing():
    langsmith_api_key = os.getenv("LANGCHAIN_API_KEY")
    if langsmith_api_key and not langsmith_api_key.startswith("your_"):
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_PROJECT"] = os.getenv("LANGCHAIN_PROJECT", "24x7-personal-assistant")
        print(f"[Config] LangSmith tracing enabled for project: {os.environ['LANGCHAIN_PROJECT']}")
    else:
        os.environ["LANGCHAIN_TRACING_V2"] = "false"
        print("[Config] LangSmith tracing key not configured or set to placeholder. Tracing disabled.")


setup_langsmith_tracing()

def validate_integration_environment() -> dict:
    """Validates presence and readiness of real integration provider environment variables."""
    return {
        "smtp": bool(os.getenv("SMTP_HOST")),
        "imap": bool(os.getenv("IMAP_HOST")),
        "tavily": bool(os.getenv("TAVILY_API_KEY")),
        "telegram": bool(os.getenv("TELEGRAM_BOT_TOKEN")),
        "whatsapp": bool(os.getenv("WHATSAPP_API_TOKEN") and os.getenv("WHATSAPP_PHONE_NUMBER_ID")),
        "google_calendar": bool(os.getenv("GOOGLE_CALENDAR_CREDENTIALS") or os.getenv("GOOGLE_CALENDAR_CLIENT_SECRET"))
    }


