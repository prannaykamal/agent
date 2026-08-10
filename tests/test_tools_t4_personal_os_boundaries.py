from pathlib import Path

PERSONAL_OS_ROOT = Path("src/personal_os")


def _read_personal_os_source() -> str:
    return "\n".join(path.read_text() for path in PERSONAL_OS_ROOT.glob("*.py"))


def test_t4_personal_os_has_no_direct_provider_calls():
    source = _read_personal_os_source().lower()
    forbidden = [
        "tavily", "duckduckgo", "ddgs", "smtplib", "imaplib",
        "whatsapp", "telegram", "google_calendar", "gmail", "requests.",
    ]
    assert all(term not in source for term in forbidden)


def test_t4_personal_os_does_not_bind_mcp_tools():
    source = _read_personal_os_source()
    forbidden = ["get_all_mcp_tools", "get_mcp_tool_catalog", "bind_tools"]
    assert all(term not in source for term in forbidden)


def test_t4_personal_os_does_not_call_memory_write_internals():
    source = _read_personal_os_source()
    forbidden = [
        "add_explicit_fact", "StructuredEpisodeRepository", "SkillVersionStore",
        "create_version", "pending_fact_candidates", "semantic_embeddings",
        "consolidation_runs", "structured_episodes", "INSERT INTO facts",
    ]
    assert all(term not in source for term in forbidden)


def test_t4_sandbox_removed_state_remains_true():
    runtime_source = "\n".join(path.read_text() for path in Path("src").rglob("*.py"))
    forbidden = ["browser_sandbox", "code_sandbox", "safe_browse_url", "capture_screenshot", "run_code", "github_merge"]
    assert all(term not in runtime_source for term in forbidden)
