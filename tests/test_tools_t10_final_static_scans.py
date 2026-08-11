import re
from pathlib import Path


ROOT = Path(".")


def _read_many(paths):
    return "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in paths if path.exists() and path.is_file())


def test_t10_removed_sandbox_runtime_files_and_routes_are_absent():
    assert not Path("src/mcp_gateway/sandboxes/browser_sandbox.py").exists()
    assert not Path("src/mcp_gateway/sandboxes/code_sandbox.py").exists()

    runtime = _read_many(Path("src").rglob("*.py"))
    assert "browser_sandbox" not in runtime
    assert "code_sandbox" not in runtime
    assert "/api/browser" not in runtime
    assert "/api/github" not in runtime

    frontend = _read_many(Path("frontend/src").rglob("*"))
    assert "/api/browser" not in frontend
    assert "/api/github" not in frontend


def test_t10_no_active_legacy_adapter_imports_or_direct_provider_calls_in_runtime():
    runtime = _read_many(list(Path("src/mcp_gateway").rglob("*.py")) + list(Path("src/tools").rglob("*.py")) + [Path("src/api/server.py")])
    assert re.search(r"search_adapters|google_calendar_sync|email_adapters", runtime) is None
    assert re.search(
        r"TAVILY_API_KEY|SMTP_|IMAP_|WHATSAPP_API_TOKEN|TELEGRAM_BOT_TOKEN|GOOGLE_CALENDAR_TOKEN|smtplib|imaplib|duckduckgo_search|DDGS|requests\.post|requests\.get",
        runtime,
    ) is None


def test_t10_memory_side_does_not_bind_user_facing_tools():
    memory_side = _read_many(list(Path("src/memory").rglob("*.py")) + [Path("src/harness/llm_router.py")])
    forbidden = ["bind_tools", "get_registered_tools", "get_all_mcp_tools", "get_all_personal_os_tools"]
    assert not any(term in memory_side for term in forbidden)


def test_t10_tools_observability_remains_read_only():
    text = Path("src/tools/observability.py").read_text(encoding="utf-8")
    forbidden = [
        "INSERT",
        "UPDATE",
        "DELETE",
        "commit(",
        "create_approval_request",
        "tools/call",
        "call_tool",
        "process_due_schedules",
        "execute_due",
    ]
    assert not any(term in text for term in forbidden)
