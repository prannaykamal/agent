import pytest

REMOVED_SANDBOX_TOOLS = {
    "safe_browse_url",
    "capture_screenshot",
    "run_code",
    "github_clone",
    "github_commit_and_push",
    "github_merge",
}



@pytest.fixture(autouse=True)
def disable_live_mcp_discovery(monkeypatch):
    monkeypatch.setattr("src.mcp_gateway.registry.load_live_mcp_tools", lambda: [])


def test_t2_get_registered_tools_excludes_removed_sandbox_tools():
    from src.harness.graph import get_registered_tools

    tools, tool_map = get_registered_tools()
    names = {tool.name for tool in tools}

    assert names.isdisjoint(REMOVED_SANDBOX_TOOLS)
    assert set(tool_map).isdisjoint(REMOVED_SANDBOX_TOOLS)


def test_t2_get_registered_tools_keeps_personal_os_and_non_removed_mcp_tools():
    from src.harness.graph import get_registered_tools

    tools, tool_map = get_registered_tools()
    names = {tool.name for tool in tools}

    assert "create_task" in names
    assert "schedule_job" in names
    assert "search_web" not in names
    assert "email_read" not in names
    assert "calendar_inspect_availability" not in names
