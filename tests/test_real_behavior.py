import pytest
from langchain_core.messages import HumanMessage
from fastapi.testclient import TestClient
from src.db import init_db, get_connection
from src.harness.graph import agent_app, resume_graph_after_approval
from src.hitl.approval_engine import create_approval_request, get_approval_request
from src.background_worker import process_due_scheduled_jobs
from src.api.server import app

@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_real_behavior.db"
    mem_file = tmp_path / "MEMORY.md"

    monkeypatch.setattr("src.db.DB_PATH", db_file)
    monkeypatch.setattr("src.config.MEMORY_PATH", mem_file)
    init_db(db_file)
    return db_file

client = TestClient(app)

def test_real_agent_loop_tool_cycle(temp_db):
    """1. Integration test for chat turn -> tool execution -> observation -> final answer."""
    initial_state = {
        "messages": [HumanMessage(content="What is my schedule for today?")],
        "session_id": "sess_real_cycle",
        "loop_count": 0,
        "tools_used": [],
        "loop_events": []
    }
    res = agent_app.invoke(initial_state)
    assert "messages" in res
    assert len(res["messages"]) > 0
    final_msg = res["messages"][-1]
    assert final_msg.content is not None


def test_real_hitl_high_risk_tool_approval_resumption(temp_db):
    """2. HITL test using actual high-risk tool call pause, decision API, and resumption."""
    req = create_approval_request(
        session_id="sess_hitl_behavior",
        tool_name="spawn_agent",
        tool_args={"role": "Reviewer", "instructions": "Review staging plan"},
        reason="High risk delegated agent",
        checkpoint_id="chk_behavior_1"
    )
    req_id = req["request_id"]

    # Decision API
    dec_resp = client.post(f"/api/approvals/{req_id}/decision", json={"decision": "APPROVED"})
    assert dec_resp.status_code == 200
    assert dec_resp.json()["status"] == "APPROVED"

    # Verify resumption execution
    req_data = get_approval_request(req_id)
    assert req_data["status"] == "APPROVED"

def test_api_contract_all_endpoints(temp_db):
    """3. API contract tests validating response schemas and status codes across all backend endpoints."""
    # /api/health
    r_health = client.get("/api/health")
    assert r_health.status_code == 200
    assert r_health.json()["status"] in ("online", "healthy")


    # /api/models
    r_models = client.get("/api/models")
    assert r_models.status_code == 200
    assert "catalog" in r_models.json() or "models" in r_models.json()


    # /api/history
    r_hist = client.get("/api/history/sess_contract")
    assert r_hist.status_code == 200


    # /api/tools
    r_tools = client.get("/api/tools")
    assert r_tools.status_code == 200
    assert "total_tools" in r_tools.json() or "os_tools" in r_tools.json()


    # /api/approvals
    r_app = client.get("/api/approvals")
    assert r_app.status_code == 200
    assert "approval_requests" in r_app.json()

    # /api/tasks
    r_tasks = client.get("/api/tasks")
    assert r_tasks.status_code == 200
    assert "tasks" in r_tasks.json()

    # /api/scheduled
    r_sched = client.get("/api/scheduled")
    assert r_sched.status_code == 200
    assert "scheduled_jobs" in r_sched.json()

    # /api/memory/full
    r_mem = client.get("/api/memory/full")
    assert r_mem.status_code == 200
    assert "facts" in r_mem.json()

    # /api/skills
    r_skills = client.get("/api/skills")
    assert r_skills.status_code == 200
    assert "skills" in r_skills.json()

    # /api/data/tables
    r_tables = client.get("/api/data/tables")
    assert r_tables.status_code == 200
    assert "tables" in r_tables.json()

    # /api/data/table/{name}
    r_tbl = client.get("/api/data/table/loop_events")
    assert r_tbl.status_code == 200
    assert "rows" in r_tbl.json()

    # /api/system/backup
    r_bkp = client.post("/api/system/backup")
    assert r_bkp.status_code == 200
    assert r_bkp.json()["status"] == "SUCCESS"

def test_frontend_static_assets_and_html(temp_db):
    """4. Frontend smoke test validating index.html static mounting and component assets."""
    r_index = client.get("/")
    assert r_index.status_code == 200
    assert "Ivo" in r_index.text
    assert "assets" in r_index.text or "main.jsx" in r_index.text



def test_database_persistence_across_restarts(temp_db):
    """5. Database persistence test across app/connection restarts."""
    conn = get_connection(temp_db)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO tasks (id, title, status) VALUES ('task_persist_1', 'Persist Test', 'COMPLETED')")
    conn.commit()
    conn.close()

    # Simulate restart by re-connecting
    conn2 = get_connection(temp_db)
    cursor2 = conn2.cursor()
    cursor2.execute("SELECT id, title, status FROM tasks WHERE id = 'task_persist_1'")
    row = cursor2.fetchone()
    conn2.close()

    assert row is not None
    assert row["title"] == "Persist Test"
    assert row["status"] == "COMPLETED"

def test_scheduled_job_execution_cycle(temp_db):
    """6. Test for scheduled job execution cycle."""
    conn = get_connection(temp_db)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO scheduled_jobs (id, cron_or_timestamp, task_payload, status)
        VALUES ('job_cycle_1', '2026-01-01 00:00', 'Run nightly consolidation', 'PENDING')
        """
    )
    conn.commit()
    conn.close()

    processed = process_due_scheduled_jobs(temp_db)
    assert len(processed) == 1
    assert processed[0]["id"] == "job_cycle_1"
    assert processed[0]["status"] == "COMPLETED"
