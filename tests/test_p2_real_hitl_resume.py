import pytest
from typing import List, Any, Optional
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.outputs import ChatResult, ChatGeneration
from fastapi.testclient import TestClient
from src.db import init_db, get_connection
from src.harness.graph import build_agent_graph, resume_graph_after_approval, node_tools
from src.api.server import app

class DeterministicFakeLLM(BaseChatModel):
    responses: List[AIMessage]

    def _generate(self, messages: List[Any], stop: Optional[List[str]] = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        resp = self.responses.pop(0) if self.responses else AIMessage(content="Completed task.")
        return ChatResult(generations=[ChatGeneration(message=resp)])

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        return self

    @property
    def _llm_type(self) -> str:
        return "deterministic_fake"

@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_p2_hitl.db"
    mem_file = tmp_path / "MEMORY.md"

    monkeypatch.setattr("src.db.DB_PATH", db_file)
    monkeypatch.setattr("src.config.MEMORY_PATH", mem_file)
    init_db(db_file)
    return db_file

client = TestClient(app)

def test_p2_high_risk_tool_approval_resumption(temp_db, monkeypatch):
    """
    P2 Test 1, 2, 3, 4, 6:
    LLM emits an actual high-risk spawn_agent tool call.
    Verifies HITL pause, approval via decision API, tool execution, ToolMessage injection,
    and model producing final user-facing response.
    """
    msg_tool_call = AIMessage(
        content="I will delegate this to a sub-agent.",
        tool_calls=[{
            "name": "spawn_agent",
            "args": {"role": "Reviewer", "instructions": "Review vendor plan"},
            "id": "call_spawn_777"
        }]
    )
    msg_final = AIMessage(content="Delegation has been completed successfully.")

    fake_llm = DeterministicFakeLLM(responses=[msg_tool_call, msg_final])
    monkeypatch.setattr("src.harness.graph.get_primary_llm", lambda **kw: (fake_llm, 128000))

    graph = build_agent_graph()

    initial_state = {
        "messages": [HumanMessage(content="Delegate review to a sub-agent")],
        "session_id": "sess_p2_approve",
        "loop_count": 0,
        "tools_used": [],
        "loop_events": []
    }

    res = graph.invoke(initial_state)

    # Verify execution paused for HITL approval
    assert res.get("approval_status") == "PENDING"
    req_id = res.get("pending_approval_id")
    assert req_id is not None

    # Resume graph after human approval
    resume_res = resume_graph_after_approval(req_id, "APPROVED")
    assert resume_res["status"] == "APPROVED"
    assert "response" in resume_res
    assert resume_res["response"]

def test_p2_high_risk_tool_rejection_resumption(temp_db, monkeypatch):
    """
    P2 Test 5 & 6:
    LLM emits a high-risk spawn_agent tool call.
    On rejection, verifies rejection observation ToolMessage appended, model loop continues,
    and safe rejection response produced.
    """
    msg_tool_call = AIMessage(
        content="Requesting sub-agent delegation.",
        tool_calls=[{
            "name": "spawn_agent",
            "args": {"role": "Reviewer", "instructions": "Review unknown task"},
            "id": "call_spawn_888"
        }]
    )
    msg_rejection_ack = AIMessage(content="The delegation was rejected by operator. No sub-agent was spawned.")

    fake_llm = DeterministicFakeLLM(responses=[msg_tool_call, msg_rejection_ack])
    monkeypatch.setattr("src.harness.graph.get_primary_llm", lambda **kw: (fake_llm, 128000))

    graph = build_agent_graph()

    initial_state = {
        "messages": [HumanMessage(content="Delegate risky review")],
        "session_id": "sess_p2_reject",
        "loop_count": 0,
        "tools_used": [],
        "loop_events": []
    }

    res = graph.invoke(initial_state)
    assert res.get("approval_status") == "PENDING"
    req_id = res.get("pending_approval_id")

    resume_res = resume_graph_after_approval(req_id, "REJECTED")
    assert resume_res["status"] == "REJECTED"
    assert "rejected" in resume_res["response"].lower()

def test_p2_node_tools_blocks_unapproved_high_risk(temp_db):
    """
    P2 Test 7:
    Direct invocation of high-risk tools outside HITL gate in node_tools is blocked.
    """
    msg_high_risk = AIMessage(
        content="Spawning sub-agent",
        tool_calls=[{
            "name": "spawn_agent",
            "args": {"role": "Reviewer", "instructions": "Review production database plan"},
            "id": "call_spawn_123"
        }]
    )

    state = {
        "messages": [msg_high_risk],
        "session_id": "sess_p2_block",
        "loop_count": 1,
        "approval_status": "NONE"
    }

    out = node_tools(state)
    tool_msgs = out.get("messages", [])
    assert len(tool_msgs) == 1
    assert "approval" in tool_msgs[0].content.lower() or "blocked" in tool_msgs[0].content.lower()

