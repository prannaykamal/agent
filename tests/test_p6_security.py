import pytest
from pathlib import Path
from src.db import init_db, get_connection
from src.hitl.classifier import classify_tool_risk
from src.hitl.approval_engine import (
    create_approval_request, process_approval_decision, generate_payload_preview
)
from src.hitl.audit_logger import log_audit_event

@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_p6_security.db"
    mem_file = tmp_path / "MEMORY.md"

    monkeypatch.setattr("src.db.DB_PATH", db_file)
    monkeypatch.setattr("src.config.MEMORY_PATH", mem_file)
    init_db(db_file)
    return db_file

def test_hitl_expanded_high_risk_classification():
    """P6 Item 5: Verifies expanded high-risk approval classification."""
    high_risk_tools = [
        "calendar_create_event", "calendar_delete_event",
        "email_send", "whatsapp_send", "telegram_send",
        "spawn_agent", "terminate_agent"
    ]
    for tool_name in high_risk_tools:
        risk, reason = classify_tool_risk(tool_name)
        assert risk == "High", f"Tool '{tool_name}' should be classified as High risk."
        assert len(reason) > 0

    for tool_name in ["github_merge", "github_commit_and_push", "run_code", "safe_browse_url", "capture_screenshot", "github_clone", "bank_transfer", "spend_money", "production_deploy", "delete_database"]:
        risk, reason = classify_tool_risk(tool_name)
        assert risk == "Blocked"
        assert len(reason) > 0

def test_approval_payload_previews():
    """P6 Item 6: Verifies human-readable payload content preview generation."""
    prev_email = generate_payload_preview("email_send", {"recipient": "user@example.com", "subject": "Meeting Notes", "body": "Here are the notes..."})
    assert "[Email Preview]" in prev_email
    assert "user@example.com" in prev_email
    assert "Meeting Notes" in prev_email

    prev_cal = generate_payload_preview("calendar_create_event", {"title": "Strategy Sync", "start_time": "2026-08-01 10:00", "end_time": "2026-08-01 11:00"})
    assert "[Calendar Preview]" in prev_cal
    assert "Strategy Sync" in prev_cal

def test_duplicate_approval_protection(temp_db):
    """P6 Item 7: Verifies approving or rejecting a request twice is blocked."""
    req = create_approval_request(
        session_id="sess_p6",
        tool_name="email_send",
        tool_args={"to": "user@example.com", "subject": "Approval", "body": "Test"},
        reason="Transfer money",
        db_path=temp_db
    )
    req_id = req["request_id"]

    # First decision (Approved)
    res_first = process_approval_decision(req_id, "APPROVED", db_path=temp_db)
    assert res_first["status"] == "APPROVED"

    # Second decision attempt (Duplicate execution protection)
    with pytest.raises(ValueError) as exc_info:
        process_approval_decision(req_id, "APPROVED", db_path=temp_db)
    assert "already been processed" in str(exc_info.value)

def test_audit_logger(temp_db):
    """P6 Item 4: Verifies audit log entries are recorded in SQLite audit_logs table."""
    audit_evt = log_audit_event(
        session_id="sess_p6",
        tool_name="email_send",
        risk_level="High",
        action="HITL_APPROVED",
        tool_args={"to": "user@example.com", "subject": "Approval", "body": "Test"},
        details="Operator approved email send",
        db_path=temp_db
    )
    assert audit_evt["action"] == "HITL_APPROVED"

    conn = get_connection(temp_db)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM audit_logs WHERE session_id = 'sess_p6'")
    rows = cursor.fetchall()
    assert len(rows) >= 1
    assert rows[0]["tool_name"] == "email_send"
    conn.close()

