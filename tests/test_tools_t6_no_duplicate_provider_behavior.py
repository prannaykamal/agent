from pathlib import Path


T6_FILES = [
    Path("src/tools/mcp_provider_config.py"),
    Path("src/tools/mcp_provider_registry.py"),
    Path("src/tools/mcp_schema.py"),
]


def test_t6_new_mcp_provider_path_does_not_import_legacy_provider_adapters():
    forbidden = [
        "search_adapters",
        "google_calendar_sync",
        "email_adapters",
        "src.mcp_gateway.search",
        "src.mcp_gateway.calendar",
        "src.mcp_gateway.communication",
    ]

    for path in T6_FILES:
        text = path.read_text(encoding="utf-8")
        for marker in forbidden:
            assert marker not in text


def test_t6_new_mcp_provider_path_does_not_implement_direct_provider_calls():
    forbidden = [
        "requests.get",
        "requests.post",
        "smtplib",
        "imaplib",
        "from duckduckgo_search",
        "import duckduckgo_search",
        "DDGS(",
        "TAVILY_API_KEY",
        "SMTP_",
        "IMAP_",
        "WHATSAPP_API_TOKEN",
        "TELEGRAM_BOT_TOKEN",
        "GOOGLE_CALENDAR_TOKEN",
    ]

    for path in T6_FILES:
        text = path.read_text(encoding="utf-8")
        for marker in forbidden:
            assert marker not in text
