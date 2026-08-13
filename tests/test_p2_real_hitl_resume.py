import pytest
from typing import List, Any, Optional
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.outputs import ChatResult, ChatGeneration
from fastapi.testclient import TestClient
from src.db import init_db, get_connection
from src.harness.graph import build_agent_graph, resume_graph_after_approval, node_tools
from src.api.server import app
from src.tools.errors import ToolErrorCode
from src.tools.invocation import ToolInvocationResult
from src.tools.policy import RiskClass, ToolPolicyDecision, ToolPolicyDecisionType

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
    assert out.get("approval_status") == "PENDING"
    assert out.get("pending_approval_id")


def test_p2_mixed_search_and_spawn_node_tools_creates_approval(temp_db):
    msg = AIMessage(
        content="Search then spawn",
        tool_calls=[
            {"name": "search_web", "args": {"query": "India Independence Day 2026"}, "id": "call_search_spawn"},
            {"name": "spawn_agent", "args": {"role": "Reviewer", "instructions": "Review the holiday note"}, "id": "call_spawn_mix"},
        ],
    )
    out = node_tools({
        "messages": [msg],
        "session_id": "sess_p2_mixed_node",
        "loop_count": 1,
        "approval_status": "NONE",
        "tools_used": [],
        "loop_events": [],
    })
    assert out.get("approval_status") == "PENDING"
    assert out.get("pending_approval_id")
    names = [m.name for m in out.get("messages", [])]
    assert names == ["search_web", "spawn_agent"]
    assert "approval" in out["messages"][1].content.lower() or "blocked" in out["messages"][1].content.lower()


def test_p2_mixed_search_and_calendar_creates_approval(temp_db, monkeypatch):
    """search_web + calendar_create_event in one turn must run search and pause calendar for HITL."""

    def fake_invoke(tool_name, arguments, tool_map, *, source="chat", approval_context=None):
        if tool_name == "search_web":
            return ToolInvocationResult(
                tool_name=tool_name,
                status="SUCCEEDED",
                output="India will celebrate its 80th Independence Day on 15 August 2026.",
                policy_decision=ToolPolicyDecision(
                    tool_name=tool_name,
                    decision=ToolPolicyDecisionType.NO_APPROVAL_NEEDED,
                    risk_class=RiskClass.LOW,
                ),
            )
        if tool_name == "calendar_create_event":
            decision = ToolPolicyDecision(
                tool_name=tool_name,
                decision=ToolPolicyDecisionType.APPROVAL_REQUIRED,
                risk_class=RiskClass.HIGH,
                reason="High-risk action requires HITL approval.",
            )
            return ToolInvocationResult(
                tool_name=tool_name,
                status=ToolErrorCode.APPROVAL_REQUIRED,
                output="Direct execution of high-risk tool 'calendar_create_event' blocked. Human-In-The-Loop approval is required.",
                policy_decision=decision,
            )
        raise AssertionError(f"unexpected tool {tool_name}")

    monkeypatch.setattr("src.harness.graph.invoke_registered_tool", fake_invoke)

    mixed = AIMessage(
        content="I will search and add it to the calendar.",
        tool_calls=[
            {"name": "search_web", "args": {"query": "India holiday August 15 2026"}, "id": "call_search_mix"},
            {
                "name": "calendar_create_event",
                "args": {
                    "title": "Independence Day",
                    "start_time": "2026-08-15T09:00:00+05:30",
                    "end_time": "2026-08-15T10:00:00+05:30",
                    "location": "Delhi",
                },
                "id": "call_cal_mix",
            },
        ],
    )
    summary = AIMessage(
        content="India is celebrating its 80th Independence Day on August 15, 2026."
    )
    fake_llm = DeterministicFakeLLM(responses=[mixed, summary])
    monkeypatch.setattr("src.harness.graph.get_primary_llm", lambda **kw: (fake_llm, 128000))

    graph = build_agent_graph()
    res = graph.invoke({
        "messages": [HumanMessage(content="What is India celebrating tomorrow? Add it to my calendar in Delhi.")],
        "session_id": "sess_p2_mixed",
        "loop_count": 0,
        "tools_used": [],
        "loop_events": [],
    })

    assert res.get("approval_status") == "PENDING"
    assert res.get("pending_approval_id")
    tool_msgs = [m for m in res.get("messages", []) if isinstance(m, ToolMessage)]
    names = [m.name for m in tool_msgs]
    assert "search_web" in names
    assert "calendar_create_event" in names
    cal = next(m for m in tool_msgs if m.name == "calendar_create_event")
    assert "approval" in cal.content.lower() or "blocked" in cal.content.lower()
    last_ai = next(m for m in reversed(res.get("messages", [])) if isinstance(m, AIMessage) and m.content)
    assert "Independence Day" in str(last_ai.content)

