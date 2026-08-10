import pytest
from fastapi.testclient import TestClient

from src.api.server import app
from src.db import init_db


REMOVED_SANDBOX_TOOLS = {
    "safe_browse_url",
    "capture_screenshot",
    "run_code",
    "github_clone",
    "github_commit_and_push",
    "github_merge",
}


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_tools_t1_catalog_compatibility.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file


@pytest.fixture(autouse=True)
def disable_live_mcp_discovery(monkeypatch):
    monkeypatch.setattr("src.mcp_gateway.registry.load_live_mcp_tools", lambda: [])


client = TestClient(app)


def test_t1_get_all_personal_os_tools_still_returns_current_tools():
    from src.personal_os.registry import get_all_personal_os_tools

    names = {tool.name for tool in get_all_personal_os_tools()}

    assert "create_task" in names
    assert "schedule_job" in names
    assert "heartbeat" in names


def test_t1_get_all_mcp_tools_filters_removed_and_unavailable_tools_after_t7():
    from src.mcp_gateway.registry import get_all_mcp_tools

    names = {tool.name for tool in get_all_mcp_tools()}

    assert "search_web" not in names
    assert "email_send" not in names
    assert names.isdisjoint(REMOVED_SANDBOX_TOOLS)


def test_t1_get_registered_tools_still_returns_active_graph_bindable_tools():
    from src.harness.graph import get_registered_tools

    tools, tool_map = get_registered_tools()
    names = {tool.name for tool in tools}

    assert tool_map
    assert "create_task" in names
    assert "search_web" not in names
    assert names.isdisjoint(REMOVED_SANDBOX_TOOLS)


def test_t1_api_tools_response_shape_remains_compatible(temp_db):
    response = client.get("/api/tools")

    assert response.status_code == 200
    data = response.json()
    assert set(data.keys()) == {"total_tools", "personal_os_tools", "mcp_tools"}
    assert data["total_tools"] == len(data["personal_os_tools"]) + len(data["mcp_tools"])
    assert all(set(item.keys()) == {"name", "description"} for item in data["personal_os_tools"])
    assert all({"name", "description", "risk_level"} <= set(item.keys()) for item in data["mcp_tools"])


def test_t1_api_tools_excludes_removed_sandbox_tools_after_t2(temp_db):
    response = client.get("/api/tools")
    data = response.json()
    mcp_names = {tool["name"] for tool in data["mcp_tools"]}

    assert mcp_names.isdisjoint(REMOVED_SANDBOX_TOOLS)


def test_t1_removed_target_metadata_exists_but_active_tools_are_filtered():
    from src.tools.registry import get_removed_tool_metadata
    from src.harness.graph import get_registered_tools

    removed_names = {item.legacy_name for item in get_removed_tool_metadata()}
    _, tool_map = get_registered_tools()

    assert REMOVED_SANDBOX_TOOLS <= removed_names
    assert set(tool_map).isdisjoint(REMOVED_SANDBOX_TOOLS)


def test_t1_removed_sandbox_api_routes_are_gone_after_t3():
    route_paths = {route.path for route in app.routes}

    assert "/" + 'api' + "/" + 'browser' + "/" + 'browse' not in route_paths
    assert "/" + 'api' + "/" + 'browser' + "/" + 'screenshot' not in route_paths
    assert "/" + 'api' + "/" + 'github' + "/" + 'clone' not in route_paths
    assert "/" + 'api' + "/" + 'github' + "/" + 'commit_and_push' not in route_paths
    assert "/" + 'api' + "/" + 'github' + "/" + 'merge' not in route_paths


def test_t1_local_provider_adapter_modules_replaced_by_t7_wrappers():
    import src.mcp_gateway.calendar as calendar
    import src.mcp_gateway.communication as communication
    import src.mcp_gateway.search as search

    assert hasattr(search, "perform_web_search")
    assert hasattr(calendar, "calendar_create_event")
    assert hasattr(communication, "email_send")
