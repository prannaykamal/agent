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
        tool_name="bank_transfer",
        tool_args={"amount": 500, "recipient": "vendor_account"},
        reason="High risk financial transaction",
        checkpoint_id="chk_real_1"
    )

    req_id = req["request_id"]
    assert req["status"] == "PENDING"

    # Test APPROVED decision
    res = resume_graph_after_approval(req_id, "APPROVED")
    assert res["status"] == "APPROVED"
    assert res["tool_name"] == "bank_transfer"
    assert "GRANTED" in res["message"]

    # Verify database update
    updated_req = get_approval_request(req_id)
    assert updated_req["status"] == "APPROVED"

def test_rejection_logs_rejection_event(temp_db):
    req = create_approval_request(
        session_id="sess_hitl_reject",
        tool_name="delete_database",
        tool_args={"target_db": "production_db"},
        reason="High risk destructive operation",
        checkpoint_id="chk_real_2"
    )

    req_id = req["request_id"]
    res = resume_graph_after_approval(req_id, "REJECTED")
    assert res["status"] == "REJECTED"
    assert res["tool_name"] == "delete_database"
    assert "DENIED" in res["message"]

    # Verify database update
    updated_req = get_approval_request(req_id)
    assert updated_req["status"] == "REJECTED"

def test_api_approval_decision_endpoint(temp_db):
    req = create_approval_request(
        session_id="sess_api_hitl",
        tool_name="production_deploy",
        tool_args={"environment": "production"},
        reason="High risk deployment",
        checkpoint_id="chk_real_3"
    )

    req_id = req["request_id"]
    response = client.post(f"/api/approvals/{req_id}/decision", json={"decision": "APPROVED"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "APPROVED"
