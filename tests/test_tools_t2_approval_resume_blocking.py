import pytest
from src.db import init_db
from src.hitl.approval_engine import create_approval_request, get_approval_request
from src.harness.graph import resume_graph_after_approval


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_tools_t2_approval_resume_blocking.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file


@pytest.fixture(autouse=True)
def disable_live_mcp_discovery(monkeypatch):
    monkeypatch.setattr("src.mcp_gateway.registry.load_live_mcp_tools", lambda: [])


def test_t2_approval_resume_blocks_removed_tool_without_invoking_sandbox(temp_db, monkeypatch):
    req = create_approval_request(
        "t2-approval",
        "github_merge",
        {"source_branch": "feature", "target_branch": "main"},
        "Old approval request for removed GitHub sandbox tool",
        "chk_removed",
        db_path=temp_db,
    )

    result = resume_graph_after_approval(req["request_id"], "APPROVED")

    assert result["status"] == "BLOCKED"
    assert result["tool_name"] == "github_merge"
    assert "removed or blocked" in result["tool_result"]
    row = get_approval_request(req["request_id"], db_path=temp_db)
    assert row["status"] == "REJECTED"


def test_t2_approval_resume_rejection_for_removed_tool_remains_safe(temp_db):
    req = create_approval_request(
        "t2-approval-reject",
        "run_code",
        {"code": "print(1)", "language": "python"},
        "Old approval request for removed code sandbox tool",
        "chk_removed_reject",
        db_path=temp_db,
    )

    result = resume_graph_after_approval(req["request_id"], "REJECTED")

    assert result["status"] == "REJECTED"
    assert result["tool_name"] == "run_code"


def test_t2_existing_non_removed_approval_flow_remains_compatible(temp_db):
    req = create_approval_request(
        "t2-approval-ok",
        "spawn_agent",
        {"role": "Reviewer", "instructions": "Review staging plan"},
        "Delegate staging review",
        "chk_allowed",
        db_path=temp_db,
    )

    result = resume_graph_after_approval(req["request_id"], "APPROVED")

    assert result["status"] == "APPROVED"
    assert "Approval GRANTED" in result["message"]



