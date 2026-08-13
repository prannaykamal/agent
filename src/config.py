import os
from pathlib import Path
from dotenv import load_dotenv
from src.memory.config import load_memory_config

# Load .env from the project root even if the process was started elsewhere.
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# Base paths
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
    """Reports provider readiness using MCP status for MCP providers and direct API status for WhatsApp/Telegram."""
    from src.external_providers.registry import get_external_provider_statuses
    from src.tools.mcp_provider_registry import get_mcp_provider_statuses

    statuses = {item["provider_id"]: item for item in get_mcp_provider_statuses(include_config=False)}
    external = {item["provider_id"]: item for item in get_external_provider_statuses()}

    def available(provider_id: str) -> bool:
        return statuses.get(provider_id, {}).get("availability_status") == "available"

    def direct_configured(provider_id: str) -> bool:
        return external.get(provider_id, {}).get("availability_status") == "configured"

    return {
        "smtp": available("gmail"),
        "imap": available("gmail"),
        "tavily": available("search_tavily"),
        "telegram": direct_configured("telegram_bot_api"),
        "whatsapp": direct_configured("whatsapp_api"),
        "google_calendar": available("google_calendar"),
    }


