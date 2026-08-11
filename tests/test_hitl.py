import pytest
from pathlib import Path
from langchain_core.messages import HumanMessage, AIMessage

from src.db import init_db
from src.hitl.classifier import classify_tool_risk
from src.hitl.approval_engine import create_approval_request, get_pending_approvals, process_approval_decision
from src.harness.graph import resume_graph_after_approval, node_hitl_check


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_hitl.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file


def test_tool_based_risk_classification():
    # Real high-risk tool classes remain covered by provider/Personal OS policy.
    assert classify_tool_risk("email_send")[0] == "High"
    assert classify_tool_risk("whatsapp_send")[0] == "High"
    assert classify_tool_risk("telegram_send")[0] == "High"
    assert classify_tool_risk("calendar_create_event")[0] == "High"
    assert classify_tool_risk("spawn_agent")[0] == "High"

    # Removed demos and sandbox tools are no longer executable.
    assert classify_tool_risk("bank_transfer")[0] == "Blocked"
    assert classify_tool_risk("delete_database")[0] == "Blocked"
    assert classify_tool_risk("run_code")[0] == "Blocked"
    assert classify_tool_risk("github_merge")[0] == "Blocked"

    assert classify_tool_risk("search_web")[0] == "Low"


def test_approval_request_lifecycle(temp_db):
    req = create_approval_request("sess_01", "email_send", {"to": "a@example.com"}, "Send external email", "chk_123", db_path=temp_db)
    assert req["status"] == "PENDING"
    req_id = req["request_id"]

    pending = get_pending_approvals("sess_01", db_path=temp_db)
    assert len(pending) == 1
    assert pending[0]["id"] == req_id

    decided = process_approval_decision(req_id, "APPROVED", db_path=temp_db)
    assert decided["status"] == "APPROVED"

    pending_after = get_pending_approvals("sess_01", db_path=temp_db)
    assert len(pending_after) == 0


def test_demo_high_risk_tool_module_removed():
    assert not Path("src/hitl/high_risk_tools.py").exists()


def test_graph_hitl_interrupt_and_pause(temp_db):
    state = {
        "messages": [
            HumanMessage(content="Please delegate this safely"),
            AIMessage(
                content="I need approval to spawn a sub-agent.",
                tool_calls=[{
                    "name": "spawn_agent",
                    "args": {"role": "Reviewer", "instructions": "Review the deployment plan"},
                    "id": "call_spawn_1",
                }],
            ),
        ],
        "session_id": "test_hitl_session",
        "loop_events": [],
    }

    result = node_hitl_check(state)
    assert result["approval_status"] == "PENDING"
    assert result["pending_approval_id"] is not None

    latest_msg = result["messages"][-1].content
    assert "[HUMAN APPROVAL REQUIRED - HIGH RISK TASK]" in latest_msg
    assert "Tool Requested: spawn_agent" in latest_msg

    pending = get_pending_approvals("test_hitl_session", db_path=temp_db)
    assert len(pending) == 1
    assert pending[0]["tool_name"] == "spawn_agent"


def test_resume_after_approval_granted(temp_db):
    req = create_approval_request(
        "sess_grant",
        "spawn_agent",
        {"role": "Reviewer", "instructions": "Review release notes"},
        "Launch sub-agent",
        "chk_test_01",
        db_path=temp_db,
    )
    res = resume_graph_after_approval(req["request_id"], "APPROVED")
    assert res["status"] == "APPROVED"
    assert "Approval GRANTED" in res["message"]


def test_resume_after_approval_rejected(temp_db):
    req = create_approval_request("sess_reject", "email_send", {"to": "a@example.com"}, "Send email", "chk_test_02", db_path=temp_db)
    res = resume_graph_after_approval(req["request_id"], "REJECTED")
    assert res["status"] == "REJECTED"
    assert "Approval DENIED" in res["message"]
