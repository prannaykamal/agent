import pytest
from typing import List, Any, Optional
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.outputs import ChatResult, ChatGeneration
from fastapi.testclient import TestClient
from src.db import init_db, get_connection
from src.harness.state import AgentState
from src.harness.graph import build_agent_graph, log_loop_event
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
    db_file = tmp_path / "test_p1_loop.db"
    mem_file = tmp_path / "MEMORY.md"

    monkeypatch.setattr("src.db.DB_PATH", db_file)
    monkeypatch.setattr("src.config.MEMORY_PATH", mem_file)
    init_db(db_file)
    return db_file

client = TestClient(app)

def test_p1_deterministic_fake_llm_tool_cycle(temp_db, monkeypatch):
    """
    P1 Test 1 & 2 & 3:
    Deterministic test with Fake LLM emitting tool call on turn 1,
    then emitting final AIMessage on turn 2.
    Verifies: USER_INPUT -> REASONING -> TOOL_REQUESTED -> TOOL_EXECUTED -> OBSERVATION -> FINAL_RESPONSE cycle,
    loop termination when no tool calls remain, and visible final response.
    """
    # Response 1: Emits tool call to calendar_inspect_availability
    msg1 = AIMessage(
        content="I will check your calendar.",
        tool_calls=[{
            "name": "calendar_inspect_availability",
            "args": {"start_date": "2026-08-01 00:00", "end_date": "2026-08-01 23:59"},
            "id": "call_fake_101"
        }]
    )
    # Response 2: Final response after tool observation
    msg2 = AIMessage(content="You have no booked events on Aug 1, 2026. All slots are free!")

    fake_llm = DeterministicFakeLLM(responses=[msg1, msg2])

    # Monkeypatch get_primary_llm to return fake_llm
    monkeypatch.setattr("src.harness.graph.get_primary_llm", lambda **kw: (fake_llm, 128000))

    graph = build_agent_graph()

    initial_state = {
        "messages": [HumanMessage(content="Am I free on Aug 1?")],
        "session_id": "sess_p1_fake",
        "loop_count": 0,
        "tools_used": [],
        "loop_events": []
    }

    res = graph.invoke(initial_state)

    messages = res.get("messages", [])
    assert len(messages) >= 3

    # Verify final AI message has no tool calls
    final_ai = messages[-1]
    assert isinstance(final_ai, AIMessage)
    assert getattr(final_ai, "tool_calls", []) == []
    assert "no booked events" in final_ai.content

    # Verify loop_events step types stored in SQLite DB
    conn = get_connection(temp_db)
    cursor = conn.cursor()
    cursor.execute("SELECT step_type, reasoning, tool_name, tool_result FROM loop_events WHERE session_id = 'sess_p1_fake' ORDER BY rowid ASC")
    rows = cursor.fetchall()
    conn.close()

    step_types = [r["step_type"] for r in rows]
    assert "USER_INPUT" in step_types
    assert "REASONING" in step_types
    assert "TOOL_REQUESTED" in step_types
    assert "TOOL_EXECUTED" in step_types
    assert "OBSERVATION" in step_types
    assert "FINAL_RESPONSE" in step_types

def test_p1_api_chat_returns_loop_trace(temp_db, monkeypatch):
    """
    P1 Test 6:
    Verifies that POST /api/chat returns complete loop_trace payload containing step event types.
    """
    msg1 = AIMessage(content="Here is your requested information.")
    fake_llm = DeterministicFakeLLM(responses=[msg1])
    monkeypatch.setattr("src.harness.graph.get_primary_llm", lambda **kw: (fake_llm, 128000))

    resp = client.post("/api/chat", json={
        "message": "Hello Assistant",
        "session_id": "sess_p1_trace"
    })

    assert resp.status_code == 200
    data = resp.json()

    assert "loop_trace" in data
    assert "response" in data
    assert len(data["loop_trace"]) > 0

    trace_types = [e["step_type"] for e in data["loop_trace"]]
    assert "USER_INPUT" in trace_types
    assert "FINAL_RESPONSE" in trace_types
