import pytest
from fastapi.testclient import TestClient

from src.api.server import app
from src.db import init_db

REMOVED_ROUTES = [
    ("post", "/" + 'api' + "/" + 'browser' + "/" + 'browse', {"url": "https://example.com"}),
    ("post", "/" + 'api' + "/" + 'browser' + "/" + 'screenshot', {"url": "https://example.com"}),
    ("post", "/" + 'api' + "/" + 'github' + "/" + 'clone', {"repo_url": "https://github.com/example/repo.git"}),
    ("post", "/" + 'api' + "/" + 'github' + "/" + 'commit_and_push', {"commit_message": "test"}),
    ("post", "/" + 'api' + "/" + 'github' + "/" + 'merge', {"source_branch": "feature"}),
]
REMOVED_TOOLS = {
    "safe_browse_url",
    "capture_screenshot",
    "run_code",
    "github_clone",
    "github_commit_and_push",
    "github_merge",
}


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_tools_t3_removed_routes.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file


@pytest.fixture(autouse=True)
def disable_live_mcp_discovery(monkeypatch):
    monkeypatch.setattr("src.mcp_gateway.registry.load_live_mcp_tools", lambda: [])


client = TestClient(app)


def test_t3_removed_routes_are_not_registered():
    route_paths = {route.path for route in app.routes}
    for _method, path, _payload in REMOVED_ROUTES:
        assert path not in route_paths


def test_t3_removed_routes_return_404(temp_db):
    for method, path, payload in REMOVED_ROUTES:
        response = getattr(client, method)(path, json=payload)
        assert response.status_code == 404


def test_t3_api_tools_active_catalog_excludes_removed_tools(temp_db):
    response = client.get("/api/tools")
    assert response.status_code == 200
    data = response.json()
    assert set(data) == {"total_tools", "personal_os_tools", "mcp_tools"}
    active_names = {item["name"] for item in data["personal_os_tools"] + data["mcp_tools"]}
    assert active_names.isdisjoint(REMOVED_TOOLS)
    assert "search_web" in active_names
    assert "create_task" in active_names


def test_t3_integrations_status_does_not_advertise_removed_sandboxes(temp_db):
    response = client.get("/api/integrations/status")
    assert response.status_code == 200
    integrations = response.json()["integrations"]
    assert "browser" not in integrations
    assert "github" not in integrations
    assert "search" in integrations
