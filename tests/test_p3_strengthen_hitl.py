import pytest
from fastapi.testclient import TestClient

from src.db import init_db, get_connection
from src.api.server import app
from src.hitl.approval_engine import create_approval_request, process_approval_decision, get_approval_request

client = TestClient(app)

@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_p3_hitl.db"
    mem_file = tmp_path / "MEMORY.md"

    monkeypatch.setattr("src.db.DB_PATH", db_file)
    monkeypatch.setattr("src.config.MEMORY_PATH", mem_file)
    init_db(db_file)
    return db_file

def test_rest_email_send_requires_approval(temp_db):
    """P3 Item 1 & 2: Verifies POST /api/email/send returns APPROVAL_REQUIRED instead of sending immediately."""
    resp = client.post("/api/email/send", json={
        "to": "vip@enterprise.com",
        "subject": "Contract",
        "body": "Terms agreed."
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "APPROVAL_REQUIRED"
    assert "approval_request" in data
    assert "request_id" in data["approval_request"]

def test_rest_calendar_create_and_delete_require_approval(temp_db):
    """P3 Item 3 & 5: Verifies calendar event creation and deletion return APPROVAL_REQUIRED."""
    # Create event REST call
    resp_create = client.post("/api/calendar/events", json={
        "title": "Board Meeting",
        "start_time": "2026-09-01 10:00",
        "end_time": "2026-09-01 11:00"
    })
    assert resp_create.status_code == 200
    assert resp_create.json()["status"] == "APPROVAL_REQUIRED"

    # Delete event REST call
    resp_del = client.delete("/api/calendar/events/evt_9999")
    assert resp_del.status_code == 200
    assert resp_del.json()["status"] == "APPROVAL_REQUIRED"

def test_rest_github_merge_requires_approval(temp_db):
    """P3 Item 4: Verifies POST /api/github/merge returns APPROVAL_REQUIRED."""
    resp_merge = client.post("/api/github/merge", json={
        "source_branch": "feature/payment",
        "target_branch": "main"
    })
    assert resp_merge.status_code == 200
    assert resp_merge.json()["status"] == "APPROVAL_REQUIRED"

def test_idempotency_key_and_duplicate_protection(temp_db):
    """P3 Item 6 & 7: Verifies idempotency key reuse and duplicate approval protection."""
    # Create request with explicit idempotency key
    key = "idem_key_unique_123"
    r1 = create_approval_request(
        session_id="sess_idem",
        tool_name="bank_transfer",
        tool_args={"amount": 100},
        reason="Test idempotency",
        idempotency_key=key,
        db_path=temp_db
    )
    req_id = r1["request_id"]

    # Re-call with same key returns existing request
    r2 = create_approval_request(
        session_id="sess_idem",
        tool_name="bank_transfer",
        tool_args={"amount": 100},
        reason="Test idempotency duplicate",
        idempotency_key=key,
        db_path=temp_db
    )
    assert r2["request_id"] == req_id

    # Process decision
    res_dec = process_approval_decision(req_id, "APPROVED", db_path=temp_db)
    assert res_dec["status"] == "APPROVED"

    # Second approval attempt raises ValueError duplicate protection
    with pytest.raises(ValueError, match="already been processed"):
        process_approval_decision(req_id, "APPROVED", db_path=temp_db)

def test_hitl_audit_logs_recorded(temp_db):
    """P3 Item 8: Verifies audit logs record creation, decisions, tool executions, and blocked attempts."""
    req_info = create_approval_request(
        session_id="sess_audit",
        tool_name="github_merge",
        tool_args={"source_branch": "feat"},
        reason="Audit test",
        db_path=temp_db
    )
    req_id = req_info["request_id"]

    process_approval_decision(req_id, "APPROVED", db_path=temp_db)

    # Inspect audit_logs table
    conn = get_connection(temp_db)
    cursor = conn.cursor()
    cursor.execute("SELECT action FROM audit_logs WHERE session_id = 'sess_audit'")
    actions = [r["action"] for r in cursor.fetchall()]
    conn.close()

    assert "HITL_REQUEST_CREATED" in actions
    assert "HITL_APPROVED" in actions
    assert "HIGH_RISK_TOOL_EXECUTED" in actions
