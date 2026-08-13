import pytest
from fastapi.testclient import TestClient
from src.db import init_db, get_connection
from src.personal_os.scheduling import schedule_job, cancel_job
from src.background_worker import process_due_scheduled_jobs
from src.api.server import app

@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_taskboard.db"
    mem_file = tmp_path / "MEMORY.md"

    monkeypatch.setattr("src.db.DB_PATH", db_file)
    monkeypatch.setattr("src.config.MEMORY_PATH", mem_file)
    init_db(db_file)
    return db_file

client = TestClient(app)

def test_taskboard_api_contract(temp_db):
    """Verifies that GET /api/tasks returns tasks, total_tasks, tasks_summary, and sub_agents."""
    conn = get_connection(temp_db)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO tasks (id, title, status, priority) VALUES ('t1', 'Prepare Report', 'PENDING', 'High')")
    cursor.execute("INSERT INTO sub_agents (agent_id, parent_session_id, role, instructions, status) VALUES ('ag1', 'sess_parent', 'Researcher', 'Research topic', 'RUNNING')")

    conn.commit()
    conn.close()

    resp = client.get("/api/tasks")
    assert resp.status_code == 200
    data = resp.json()
    assert "tasks" in data
    assert "total_tasks" in data
    assert "tasks_summary" in data
    assert "sub_agents" in data
    assert len(data["tasks"]) == 1
    assert "Prepare Report" in data["tasks_summary"]
    assert "progress" in data["tasks"][0]
    assert len(data["sub_agents"]) == 1
    assert data["sub_agents"][0]["role"] == "Researcher"

def test_scheduled_job_lifecycle(temp_db):
    """Verifies schedule_job creates PENDING job, background worker processes it, and cancel_job updates to CANCELLED."""
    # 1. Schedule a job
    res_sched = schedule_job.invoke({"cron_or_timestamp": "2026-01-01 10:00", "task_payload": "Execute data sync"})
    assert "registered" in res_sched

    # 2. Verify status is PENDING in GET /api/scheduled
    resp_get = client.get("/api/scheduled")
    assert resp_get.status_code == 200
    jobs = resp_get.json()["scheduled_jobs"]
    assert len(jobs) == 1
    assert jobs[0]["status"] == "PENDING"
    job_id = jobs[0]["id"]

    # 3. Background worker execution
    processed = process_due_scheduled_jobs(temp_db)
    assert len(processed) == 1
    assert processed[0]["id"] == job_id
    assert processed[0]["status"] == "COMPLETED"

    # 4. Schedule another job and cancel it
    res_sched2 = schedule_job.invoke({"cron_or_timestamp": "2026-12-31 23:59", "task_payload": "Future job"})
    resp_get2 = client.get("/api/scheduled")
    jobs2 = resp_get2.json()["scheduled_jobs"]
    new_job_id = [j["id"] for j in jobs2 if j["status"] == "PENDING"][0]

    res_cancel = cancel_job.invoke({"job_id": new_job_id})
    assert "successfully cancelled" in res_cancel

    # Verify status CANCELLED
    resp_get3 = client.get("/api/scheduled")
    jobs3 = resp_get3.json()["scheduled_jobs"]
    cancelled_job = [j for j in jobs3 if j["id"] == new_job_id][0]
    assert cancelled_job["status"] == "CANCELLED"


def test_task_create_and_update_via_api(temp_db):
    created = client.post("/api/tasks", json={"title": "Sidebar task", "description": "From UI", "priority": "High"})
    assert created.status_code == 200
    listed = client.get("/api/tasks")
    assert listed.status_code == 200
    tasks = listed.json()["tasks"]
    match = next(item for item in tasks if item["title"] == "Sidebar task")
    updated = client.patch(f"/api/tasks/{match['id']}", json={"status": "COMPLETED", "progress": 100})
    assert updated.status_code == 200
    after = client.get("/api/tasks").json()["tasks"]
    assert next(item for item in after if item["id"] == match["id"])["status"] == "COMPLETED"
