import pytest
from langchain_core.tools import BaseTool
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from src.api.server import app
from src.db import init_db
from src.harness.graph import node_tools
from src.hitl.classifier import classify_tool_risk
from src.mcp_gateway.registry import get_mcp_tool_risk

REMOVED_SANDBOX_TOOLS = {
    "safe_browse_url",
    "capture_screenshot",
    "run_code",
    "github_clone",
    "github_commit_and_push",
    "github_merge",
}

@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_tools_t2_removed_tool_blocking.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file

client = TestClient(app)

def test_t2_removed_tools_classify_as_blocked():
    for name in REMOVED_SANDBOX_TOOLS:
        risk, reason = classify_tool_risk(name)
        assert risk == "Blocked"
        assert "Removed tool" in reason
        assert get_mcp_tool_risk(name) == "Blocked"

def test_t2_run_code_is_not_low_risk_anymore():
    assert classify_tool_risk("run_code")[0] == "Blocked"

def test_t2_graph_tool_execution_blocks_removed_tool_without_invoking_old_function(temp_db, monkeypatch):
    def fail_if_called(self, _args, *args, **kwargs):
        if getattr(self, "name", "") in REMOVED_SANDBOX_TOOLS:
            raise AssertionError("old browser sandbox function must not be called")
        return original_invoke(self, _args, *args, **kwargs)

    original_invoke = BaseTool.invoke
    monkeypatch.setattr(BaseTool, "invoke", fail_if_called)
    call_msg = AIMessage(
        content="",
        tool_calls=[{"name": "safe_browse_url", "args": {"url": "https://example.com"}, "id": "call_removed_1"}],
    )

    result = node_tools({
        "messages": [call_msg],
        "session_id": "t2-removed-graph",
        "loop_count": 1,
        "loop_events": [],
        "tools_used": [],
    })

    tool_messages = result["messages"]
    assert len(tool_messages) == 1
    assert "removed or blocked" in tool_messages[0].content
    assert "No execution occurred" in tool_messages[0].content
    assert result["tools_used"] == []

def test_t2_api_browser_and_github_routes_are_removed_after_t3(temp_db):
    browse = client.post("/" + 'api' + "/" + 'browser' + "/" + 'browse', json={"url": "https://example.com"})
    clone = client.post("/" + 'api' + "/" + 'github' + "/" + 'clone', json={"repo_url": "https://github.com/example/repo.git"})

    assert browse.status_code == 404
    assert clone.status_code == 404

def test_t2_non_removed_tool_risk_still_works():
    assert classify_tool_risk("search_web")[0] == "Low"
    assert classify_tool_risk("email_send")[0] == "High"
    assert classify_tool_risk("spawn_agent")[0] == "High"
