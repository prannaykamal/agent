from langchain_core.messages import AIMessage

from src.db import init_db
from src.harness.graph import node_tools
from src.tools.policy import evaluate_tool_policy


def test_t8_removed_tools_are_blocked_by_policy():
    for name in ["safe_browse_url", "capture_screenshot", "run_code", "github_clone", "github_commit_and_push", "github_merge"]:
        decision = evaluate_tool_policy(name, {})
        assert decision.blocked
        assert decision.reason_code == "removed_tool"


def test_t8_graph_tool_execution_blocks_removed_tool_without_call(tmp_path, monkeypatch):
    db_file = tmp_path / "removed_graph.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    msg = AIMessage(content="", tool_calls=[{"name": "run_code", "args": {"code": "print(1)"}, "id": "call_removed"}])
    result = node_tools({"messages": [msg], "session_id": "sess", "loop_count": 1})
    assert len(result["messages"]) == 1
    assert "removed or blocked" in result["messages"][0].content
    assert result["tools_used"] == []