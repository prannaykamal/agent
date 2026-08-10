import pytest
from pathlib import Path
from langchain_core.messages import HumanMessage, AIMessage

from src.db import init_db
from src.hitl.classifier import classify_tool_risk
from src.hitl.approval_engine import create_approval_request, get_pending_approvals, process_approval_decision
from src.hitl.high_risk_tools import bank_transfer, spend_money, production_deploy, delete_database, delete_files
from src.harness.graph import agent_app, resume_graph_after_approval

@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_hitl.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file

def test_tool_based_risk_classification():
    # High Risk Tools
    assert classify_tool_risk("bank_transfer")[0] == "High"
    assert classify_tool_risk("spend_money")[0] == "High"
    assert classify_tool_risk("production_deploy")[0] == "High"
    assert classify_tool_risk("delete_database")[0] == "High"
    assert classify_tool_risk("send_email")[0] == "High"
    assert classify_tool_risk("email_send")[0] == "High"
    assert classify_tool_risk("whatsapp_send")[0] == "High"
    assert classify_tool_risk("telegram_send")[0] == "High"
    assert classify_tool_risk("delete_files")[0] == "High"
    assert classify_tool_risk("github_merge")[0] == "Blocked"

    # Medium, Low, and blocked removed tools
    assert classify_tool_risk("spawn_agent")[0] == "High"
    assert classify_tool_risk("search_web")[0] == "Low"
    assert classify_tool_risk("run_code")[0] == "Blocked"

def test_approval_request_lifecycle(temp_db):
    req = create_approval_request("sess_01", "bank_transfer", {"amount": 500}, "Transfer money to vendor", "chk_123", db_path=temp_db)
    assert req["status"] == "PENDING"
    req_id = req["request_id"]

    pending = get_pending_approvals("sess_01", db_path=temp_db)
    assert len(pending) == 1
    assert pending[0]["id"] == req_id

    decided = process_approval_decision(req_id, "APPROVED", db_path=temp_db)
    assert decided["status"] == "APPROVED"

    pending_after = get_pending_approvals("sess_01", db_path=temp_db)
    assert len(pending_after) == 0

def test_high_risk_native_tools():
    bt_res = bank_transfer.invoke({"recipient_account": "ACC123", "amount": 250.0})
    assert "[Bank Transfer Executed]" in bt_res

    sm_res = spend_money.invoke({"amount": 99.0, "service": "Cloud Hosting"})
    assert "[Spend Money Executed]" in sm_res

    deploy_res = production_deploy.invoke({"environment": "production", "build_tag": "v2.1"})
    assert "[Production Deploy Executed]" in deploy_res

    del_db_res = delete_database.invoke({"target_db": "test_db"})
    assert "[Delete Database Executed]" in del_db_res

    del_files_res = delete_files.invoke({"file_paths": "/tmp/old_data.csv"})
    assert "[Delete Files Executed]" in del_files_res

def test_graph_hitl_interrupt_and_pause(temp_db):
    input_state = {
        "messages": [HumanMessage(content="Please do a bank_transfer of $500 to account #1234")],
        "session_id": "test_hitl_session",
        "summary": "",
        "token_count": 0,
        "retrieval_triggered": False,
        "retrieved_memories": [],
        "pending_approval_id": None,
        "approval_status": None
    }

    result = agent_app.invoke(input_state)
    assert result["approval_status"] == "PENDING"
    assert result["pending_approval_id"] is not None

    latest_msg = result["messages"][-1].content
    assert "[HUMAN APPROVAL REQUIRED - HIGH RISK TASK]" in latest_msg
    assert "Tool Requested: bank_transfer" in latest_msg

    # Verify pending approval request exists in DB
    pending = get_pending_approvals("test_hitl_session", db_path=temp_db)
    assert len(pending) == 1
    assert pending[0]["tool_name"] == "bank_transfer"

def test_resume_after_approval_granted(temp_db):
    req = create_approval_request("sess_grant", "delete_database", {"target_db": "staging"}, "Purge staging DB", "chk_test_01", db_path=temp_db)
    req_id = req["request_id"]

    res = resume_graph_after_approval(req_id, "APPROVED")
    assert res["status"] == "APPROVED"
    assert "Approval GRANTED" in res["message"]

def test_resume_after_approval_rejected(temp_db):
    req = create_approval_request("sess_reject", "production_deploy", {"build_tag": "v9.9"}, "Deploy untested build", "chk_test_02", db_path=temp_db)
    req_id = req["request_id"]

    res = resume_graph_after_approval(req_id, "REJECTED")
    assert res["status"] == "REJECTED"
    assert "Approval DENIED" in res["message"]
