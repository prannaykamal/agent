import pytest
from fastapi.testclient import TestClient

from src.api.server import app
from src.db import init_db
from src.personal_os.tasks import create_task


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_tools_t4_personal_os_api.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file


client = TestClient(app)


def test_t4_api_tools_remains_compatible_and_excludes_synthetic(temp_db):
    response = client.get("/api/tools")
    assert response.status_code == 200
    data = response.json()
    assert set(data) == {"total_tools", "personal_os_tools", "mcp_tools"}
    names = {item["name"] for item in data["personal_os_tools"]}
    assert "create_task" in names
    assert "schedule_job" in names
    assert "sleep" not in names
    assert "wake" not in names
    assert "acquire_context" not in names


def test_t4_personal_os_status_endpoint(temp_db):
    response = client.get("/api/tools/personal-os/status")
    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "personal_os"
    assert data["implementation_type"] == "local"
    assert "tasks" in data
    assert "non_responsibilities" in data


def test_t4_personal_os_actions_endpoint_includes_deprecated_metadata(temp_db):
    response = client.get("/api/tools/personal-os/actions")
    assert response.status_code == 200
    actions = response.json()["actions"]
    by_name = {item["legacy_name"]: item for item in actions}
    assert by_name["create_task"]["implementation_type"] == "local"
    assert by_name["sleep"]["implementation_type"] == "removed"
    assert by_name["sleep"]["approval_policy"] == "blocked"


def test_t4_personal_os_audit_endpoint(temp_db):
    create_task.invoke({"title": "API audit task", "description": "", "priority": "Medium"})
    response = client.get("/api/tools/personal-os/audit")
    assert response.status_code == 200
    data = response.json()
    assert data["total_events"] >= 1
    assert data["audit_events"][0]["tool_name"] == "create_task"


def test_t4_api_tasks_compatibility(temp_db):
    response = client.get("/api/tasks")
    assert response.status_code == 200
    data = response.json()
    assert "tasks" in data
    assert "total_tasks" in data
    assert "tasks_summary" in data
    assert "sub_agents" in data
