import pytest

from src.db import init_db
from src.hitl.approval_engine import create_approval_request, get_approval_request
from src.harness.graph import resume_graph_after_approval


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_tools_t8_approval_resume.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file


@pytest.fixture(autouse=True)
def no_live_mcp(monkeypatch):
    monkeypatch.setattr("src.mcp_gateway.registry.load_live_mcp_tools", lambda: [])


def test_t8_removed_tool_approval_resume_fails_closed(temp_db):
    req = create_approval_request("sess", "run_code", {"code": "print(1)"}, "old removed tool", db_path=temp_db)
    result = resume_graph_after_approval(req["request_id"], "APPROVED")
    assert result["status"] == "BLOCKED"
    assert "removed" in result["message"].lower() or "blocked" in result["message"].lower()
    assert get_approval_request(req["request_id"], db_path=temp_db)["status"] == "REJECTED"


def test_t8_unavailable_mcp_approval_resume_fails_closed(temp_db):
    req = create_approval_request("sess", "email_send", {"recipient": "a@example.com", "body": "hi"}, "send email", db_path=temp_db)
    result = resume_graph_after_approval(req["request_id"], "APPROVED")
    assert result["status"] == "UNAVAILABLE"
    assert "unavailable" in result["message"].lower()
    assert get_approval_request(req["request_id"], db_path=temp_db)["status"] == "REJECTED"


def test_t8_non_removed_high_risk_personal_os_approval_flow_still_works(temp_db):
    req = create_approval_request(
        "sess",
        "spawn_agent",
        {"role": "Reviewer", "instructions": "Review staging plan"},
        "delegate",
        db_path=temp_db,
    )
    result = resume_graph_after_approval(req["request_id"], "APPROVED")
    assert result["status"] == "APPROVED"
    assert "Approval GRANTED" in result["message"]

