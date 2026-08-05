import pytest
from fastapi.testclient import TestClient

from src.api.server import app
from src.db import init_db


BASELINE_PERSONAL_OS_TOOLS = {
    "create_task",
    "update_task",
    "cancel_task",
    "list_tasks",
    "spawn_agent",
    "schedule_job",
    "cancel_job",
    "heartbeat",
}

BASELINE_LOCAL_ADAPTER_MCP_TOOLS = {
    "search_web",
    "calendar_inspect_availability",
    "calendar_propose_event",
    "calendar_create_event",
    "calendar_update_event",
    "calendar_delete_event",
    "email_read",
    "email_search",
    "email_draft",
    "email_send",
    "whatsapp_read",
    "whatsapp_send",
    "telegram_read",
    "telegram_send",
}

BASELINE_BROWSER_SANDBOX_TOOLS_TO_REMOVE = {
    "safe_browse_url",
    "capture_screenshot",
}

BASELINE_CODE_SANDBOX_TOOLS_TO_REMOVE = {
    "run_code",
    "github_clone",
    "github_commit_and_push",
    "github_merge",
}


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_tools_t0_baseline_registry.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file


@pytest.fixture(autouse=True)
def disable_live_mcp_discovery(monkeypatch):
    # T0 documents current local/static exposure without depending on external MCP servers.
    monkeypatch.setattr("src.mcp_gateway.registry.load_live_mcp_tools", lambda: [])


client = TestClient(app)


def test_t0_migration_baseline_current_tool_registry_loads_successfully():
    from src.harness.graph import get_registered_tools

    tools, tool_map = get_registered_tools()

    assert tools
    assert tool_map
    assert len(tools) == len(tool_map)


def test_t0_migration_baseline_personal_os_tools_are_currently_present():
    from src.personal_os.registry import get_all_personal_os_tools

    tool_names = {tool.name for tool in get_all_personal_os_tools()}

    assert BASELINE_PERSONAL_OS_TOOLS <= tool_names


def test_t0_migration_baseline_local_adapter_mcp_tools_are_currently_present():
    from src.mcp_gateway.registry import get_all_mcp_tools

    tool_names = {tool.name for tool in get_all_mcp_tools()}

    assert BASELINE_LOCAL_ADAPTER_MCP_TOOLS <= tool_names


def test_t0_migration_baseline_browser_sandbox_tools_currently_exposed_to_remove_later():
    from src.mcp_gateway.registry import get_all_mcp_tools

    tool_names = {tool.name for tool in get_all_mcp_tools()}

    # Expected current-state baseline only. T3 should invert this assertion.
    assert BASELINE_BROWSER_SANDBOX_TOOLS_TO_REMOVE <= tool_names


def test_t0_migration_baseline_code_sandbox_tools_currently_exposed_to_remove_later():
    from src.mcp_gateway.registry import get_all_mcp_tools

    tool_names = {tool.name for tool in get_all_mcp_tools()}

    # Expected current-state baseline only. T3 should invert this assertion.
    assert BASELINE_CODE_SANDBOX_TOOLS_TO_REMOVE <= tool_names


def test_t0_migration_baseline_api_tools_shape_and_groups_are_unchanged(temp_db):
    response = client.get("/api/tools")

    assert response.status_code == 200
    data = response.json()
    assert set(data.keys()) == {"total_tools", "personal_os_tools", "mcp_tools"}
    assert isinstance(data["total_tools"], int)
    assert isinstance(data["personal_os_tools"], list)
    assert isinstance(data["mcp_tools"], list)
    assert data["total_tools"] == len(data["personal_os_tools"]) + len(data["mcp_tools"])


def test_t0_migration_baseline_api_tools_includes_current_groups_and_sandbox_targets(temp_db):
    response = client.get("/api/tools")
    data = response.json()

    personal_os_names = {tool["name"] for tool in data["personal_os_tools"]}
    mcp_names = {tool["name"] for tool in data["mcp_tools"]}

    assert BASELINE_PERSONAL_OS_TOOLS <= personal_os_names
    assert BASELINE_LOCAL_ADAPTER_MCP_TOOLS <= mcp_names

    # Expected current-state baseline only. These are target-for-removal later.
    assert BASELINE_BROWSER_SANDBOX_TOOLS_TO_REMOVE <= mcp_names
    assert BASELINE_CODE_SANDBOX_TOOLS_TO_REMOVE <= mcp_names
