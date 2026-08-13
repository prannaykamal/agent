import pytest
from fastapi.testclient import TestClient

from src.api.server import app
from src.db import init_db
from src.tools.registry_types import ImplementationType

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
    db_file = tmp_path / "test_tools_t2_active_catalog_filtering.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file

client = TestClient(app)

def test_t2_api_tools_active_catalog_excludes_removed_sandbox_tools(temp_db):
    response = client.get("/api/tools")

    assert response.status_code == 200
    data = response.json()
    assert set(data.keys()) == {"total_tools", "personal_os_tools", "mcp_tools", "external_api_tools"}
    assert data["total_tools"] == len(data["personal_os_tools"]) + len(data["mcp_tools"]) + len(data["external_api_tools"])

    mcp_names = {tool["name"] for tool in data["mcp_tools"]}
    assert mcp_names.isdisjoint(REMOVED_SANDBOX_TOOLS)

def test_t2_api_tools_keeps_personal_os_and_non_removed_mcp_tools(temp_db):
    data = client.get("/api/tools").json()
    personal_names = {tool["name"] for tool in data["personal_os_tools"]}
    mcp_names = {tool["name"] for tool in data["mcp_tools"]}

    assert "create_task" in personal_names
    assert "schedule_job" in personal_names
    assert "search_web" not in mcp_names
    assert "email_send" not in mcp_names

def test_t2_removed_target_metadata_remains_available_and_disabled():
    from src.tools.registry import get_removed_tool_metadata

    removed = {item.legacy_name: item for item in get_removed_tool_metadata()}
    assert REMOVED_SANDBOX_TOOLS <= set(removed)
    for name in REMOVED_SANDBOX_TOOLS:
        item = removed[name]
        assert item.implementation_type == ImplementationType.REMOVED
        assert item.enabled is False
        assert item.removal_reason

def test_t2_removed_target_metadata_is_not_bindable():
    from src.tools.registry import get_bindable_tool_metadata, get_tool_metadata_by_legacy_name

    bindable_names = {item.legacy_name for item in get_bindable_tool_metadata()}
    assert bindable_names.isdisjoint(REMOVED_SANDBOX_TOOLS)
    assert get_tool_metadata_by_legacy_name("run_code").implementation_type == ImplementationType.REMOVED

