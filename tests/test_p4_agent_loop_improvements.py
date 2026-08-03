import pytest
from unittest.mock import MagicMock
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

from src.harness.graph import agent_app, should_continue
from src.harness.state import AgentState
from src.db import init_db

@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_p4_loop.db"
    mem_file = tmp_path / "MEMORY.md"

    monkeypatch.setattr("src.db.DB_PATH", db_file)
    monkeypatch.setattr("src.config.MEMORY_PATH", mem_file)
    init_db(db_file)
    return db_file

def make_initial_state(user_input: str, session_id: str = "sess_test") -> AgentState:
    return {
        "messages": [HumanMessage(content=user_input)],
        "session_id": session_id,
        "summary": "",
        "token_count": 0,
        "retrieval_triggered": False,
        "retrieved_memories": [],
        "pending_approval_id": None,
        "approval_status": None,
        "provider": "openai",
        "model_name": "gpt-4o-mini",
        "fact_candidates": [],
        "loop_count": 0,
        "tools_used": [],
        "loop_events": []
    }

def test_multi_tool_calls_in_single_assistant_response(temp_db, monkeypatch):
    """P4 Item 6: Verifies processing of multi-tool calls in a single assistant response."""
    multi_call_msg = AIMessage(
        content="Inspecting system status and fetching messages.",
        tool_calls=[
            {"name": "search_web", "args": {"query": "python"}, "id": "call_multi_1"},
            {"name": "email_read", "args": {"limit": 2}, "id": "call_multi_2"}
        ]
    )

    mock_llm = MagicMock()
    mock_llm.bind_tools.return_value.invoke.return_value = multi_call_msg
    monkeypatch.setattr("src.harness.graph.get_primary_llm", lambda provider, model_name: (mock_llm, 128000))

    state = make_initial_state(user_input="Run multiple tools", session_id="sess_multi_tool")
    res = agent_app.invoke(state)

    assert "loop_events" in res
    events = res["loop_events"]
    req_events = [e for e in events if e.get("step_type") == "TOOL_REQUESTED"]
    assert len(req_events) >= 2
    tool_names = [e["tool_name"] for e in req_events]
    assert "search_web" in tool_names
    assert "email_read" in tool_names

def test_tool_execution_error_recovery(temp_db, monkeypatch):
    """P4 Item 7: Verifies graph error recovery when a tool raises or returns an error."""
    fail_call_msg = AIMessage(
        content="Executing search with invalid query.",
        tool_calls=[{"name": "search_web", "args": {"query": ""}, "id": "call_fail_1"}]
    )
    recovery_msg = AIMessage(content="Observed empty query notice. Retrying with fallback search term 'antigravity'.")

    mock_llm = MagicMock()
    mock_llm.bind_tools.return_value.invoke.side_effect = [fail_call_msg, recovery_msg]
    monkeypatch.setattr("src.harness.graph.get_primary_llm", lambda provider, model_name: (mock_llm, 128000))

    state = make_initial_state(user_input="Search empty", session_id="sess_error_recovery")
    res = agent_app.invoke(state)

    messages = res.get("messages", [])
    assert len(messages) >= 2
    assert "antigravity" in str(messages[-1].content) or "Retrying" in str(messages[-1].content)

def test_max_iteration_stopping_behavior(temp_db):
    """P4 Item 8: Verifies max-iteration stopping behavior (loop_count >= 10 transitions to consolidate/end)."""
    state_at_limit = make_initial_state(user_input="Loop forever test", session_id="sess_max_iter")
    state_at_limit["loop_count"] = 10
    state_at_limit["messages"] = [
        HumanMessage(content="Loop forever"),
        AIMessage(content="Tool call loop", tool_calls=[{"name": "search_web", "args": {"query": "loop"}, "id": "call_infinite"}])
    ]

    next_step = should_continue(state_at_limit)
    assert next_step == "consolidate"
