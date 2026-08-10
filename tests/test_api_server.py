import pytest
from fastapi.testclient import TestClient
from src.db import init_db
from src.api.server import app

@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_api_expanded.db"
    mem_file = tmp_path / "MEMORY.md"

    monkeypatch.setattr("src.db.DB_PATH", db_file)
    monkeypatch.setattr("src.config.MEMORY_PATH", mem_file)
    init_db(db_file)
    return db_file

client = TestClient(app)

def test_api_health(temp_db):
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "online"
    assert "heartbeat" in data

def test_api_chat(temp_db):
    response = client.post(
        "/api/chat",
        json={
            "message": "Hello assistant",
            "session_id": "test_api_session",
            "provider": "anthropic",
            "model_name": "claude-3-5-sonnet-latest"
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert "response" in data
    assert data["session_id"] == "test_api_session"

def test_api_models(temp_db):
    response = client.get("/api/models")
    assert response.status_code == 200
    data = response.json()
    assert "catalog" in data
    assert "openai" in data["catalog"]
    assert "anthropic" in data["catalog"]
    assert "gemini" in data["catalog"]
    assert "grok" in data["catalog"]

def test_api_memory_and_full(temp_db):
    # Add fact
    add_resp = client.post("/api/memory/fact", json={"category": "user_pref", "fact_text": "Prefers FastAPI"})
    assert add_resp.status_code == 200

    # Get memory
    get_resp = client.get("/api/memory")
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert len(data["facts"]) >= 1

    # Get full memory
    full_resp = client.get("/api/memory/full?query=FastAPI")
    assert full_resp.status_code == 200
    full_data = full_resp.json()
    assert "facts" in full_data
    assert "soul_md" in full_data
    assert "skill_md" in full_data

def test_api_tools_catalog(temp_db):
    resp = client.get("/api/tools")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_tools"] >= 1
    assert "personal_os_tools" in data
    assert "mcp_tools" in data

def test_api_tasks(temp_db):
    resp = client.get("/api/tasks")
    assert resp.status_code == 200
    data = resp.json()
    assert "tasks" in data
    assert "total_tasks" in data

def test_api_scheduled_jobs_and_delete(temp_db):
    # Create scheduled job
    create_resp = client.post("/api/scheduled", json={"cron_or_timestamp": "0 9 * * *", "task_payload": "E-mail monitor task"})
    assert create_resp.status_code == 200
    assert create_resp.json()["status"] == "success"

    # Get scheduled jobs
    get_resp = client.get("/api/scheduled")
    assert get_resp.status_code == 200
    jobs = get_resp.json()["scheduled_jobs"]
    assert len(jobs) >= 1
    job_id = jobs[0]["id"]
    assert jobs[0]["task_payload"] == "E-mail monitor task"

    # Delete scheduled job
    del_resp = client.delete(f"/api/scheduled/{job_id}")
    assert del_resp.status_code == 200
    assert del_resp.json()["status"] == "success"
