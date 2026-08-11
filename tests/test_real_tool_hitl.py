import pytest
from fastapi.testclient import TestClient
from src.db import init_db, get_connection
from src.hitl.approval_engine import create_approval_request, get_approval_request
from src.harness.graph import resume_graph_after_approval
from src.api.server import app

@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_real_hitl.db"
    mem_file = tmp_path / "MEMORY.md"

    monkeypatch.setattr("src.db.DB_PATH", db_file)
    monkeypatch.setattr("src.config.MEMORY_PATH", mem_file)
    init_db(db_file)
    return db_file

client = TestClient(app)

def test_approval_resumption_executes_tool(temp_db):
    req = create_approval_request(
        session_id="sess_hitl_real",
        tool_name="spawn_agent",
        tool_args={"role": "Reviewer", "instructions": "Review vendor account plan"},
        reason="High risk sub-agent lifecycle action",
        checkpoint_id="chk_real_1"
    )

    req_id = req["request_id"]
    assert req["status"] == "PENDING"

    # Test APPROVED decision
    res = resume_graph_after_approval(req_id, "APPROVED")
    assert res["status"] == "APPROVED"
    assert res["tool_name"] == "spawn_agent"
    assert "GRANTED" in res["message"]

    # Verify database update
    updated_req = get_approval_request(req_id)
    assert updated_req["status"] == "APPROVED"

def test_rejection_logs_rejection_event(temp_db):
    req = create_approval_request(
        session_id="sess_hitl_reject",
        tool_name="email_send",
        tool_args={"to": "ops@example.com", "subject": "Reject", "body": "Test"},
        reason="High risk external send",
        checkpoint_id="chk_real_2"
    )

    req_id = req["request_id"]
    res = resume_graph_after_approval(req_id, "REJECTED")
    assert res["status"] == "REJECTED"
    assert res["tool_name"] == "email_send"
    assert "DENIED" in res["message"]

    # Verify database update
    updated_req = get_approval_request(req_id)
    assert updated_req["status"] == "REJECTED"

def test_api_approval_decision_endpoint(temp_db):
    req = create_approval_request(
        session_id="sess_api_hitl",
        tool_name="spawn_agent",
        tool_args={"role": "Reviewer", "instructions": "Review approval endpoint"},
        reason="High risk sub-agent lifecycle action",
        checkpoint_id="chk_real_3"
    )

    req_id = req["request_id"]
    response = client.post(f"/api/approvals/{req_id}/decision", json={"decision": "APPROVED"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "APPROVED"

