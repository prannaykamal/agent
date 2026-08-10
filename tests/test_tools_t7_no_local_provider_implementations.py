from pathlib import Path


RUNTIME_FILES = [
    Path("src/mcp_gateway/search.py"),
    Path("src/mcp_gateway/calendar.py"),
    Path("src/mcp_gateway/communication.py"),
    Path("src/tools/mcp_invocation.py"),
    Path("src/api/server.py"),
]


def test_t7_deleted_legacy_provider_adapter_files_are_gone():
    assert not Path("src/mcp_gateway/search_adapters.py").exists()
    assert not Path("src/mcp_gateway/google_calendar_sync.py").exists()
    assert not Path("src/mcp_gateway/email_adapters.py").exists()


def test_t7_runtime_provider_paths_do_not_contain_direct_provider_implementations():
    forbidden = [
        "TAVILY_API_KEY",
        "SMTP_",
        "IMAP_",
        "WHATSAPP_API_TOKEN",
        "TELEGRAM_BOT_TOKEN",
        "GOOGLE_CALENDAR_TOKEN",
        "smtplib",
        "imaplib",
        "duckduckgo_search",
        "DDGS",
        "requests.post",
        "requests.get",
        "urlopen",
    ]

    for path in RUNTIME_FILES:
        text = path.read_text(encoding="utf-8")
        for marker in forbidden:
            assert marker not in text


def test_t7_legacy_provider_imports_are_absent_from_runtime():
    forbidden = ["search_adapters", "google_calendar_sync", "email_adapters"]

    for path in RUNTIME_FILES:
        text = path.read_text(encoding="utf-8")
        for marker in forbidden:
            assert marker not in text


def test_t7_registry_does_not_bind_unavailable_target_provider_tools(monkeypatch):
    monkeypatch.setattr("src.mcp_gateway.registry.load_live_mcp_tools", lambda: [])

    from src.mcp_gateway.registry import get_all_mcp_tools

    names = {tool.name for tool in get_all_mcp_tools()}

    assert "search_web" not in names
    assert "email_send" not in names
    assert "calendar_create_event" not in names


def test_t7_compatibility_wrappers_bind_only_when_provider_available(monkeypatch):
    monkeypatch.setattr("src.mcp_gateway.registry.load_live_mcp_tools", lambda: [])
    monkeypatch.setattr("src.mcp_gateway.registry._available_provider_ids", lambda: {"gmail", "search"})

    from src.mcp_gateway.registry import get_all_mcp_tools, get_mcp_gateway_tool_metadata

    names = {tool.name for tool in get_all_mcp_tools()}
    metadata = {item.legacy_name: item for item in get_mcp_gateway_tool_metadata()}

    assert "email_send" in names
    assert "search_web" in names
    assert "calendar_create_event" not in names
    assert metadata["email_send"].provider == "gmail"
    assert metadata["email_send"].provider_managed is True
    assert metadata["email_send"].observability_metadata["legacy_local_adapter_backed"] is False
