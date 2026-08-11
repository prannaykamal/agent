import pytest
from pathlib import Path
from langchain_core.messages import HumanMessage, AIMessage

from src.db import init_db
from src.memory.semantic import add_semantic_fact, sync_memory_md
from src.orchestration.tools import spawn_agent
from src.personal_os.tasks import create_task
from src.personal_os.concurrency import lock_resource, unlock_resource
from src.personal_os.event_bus import publish_event
from src.mcp_gateway.search import search_web
from src.hitl.approval_engine import get_pending_approvals
from src.harness.graph import agent_app, resume_graph_after_approval

@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_e2e.db"
    mem_file = tmp_path / "MEMORY.md"

    monkeypatch.setattr("src.db.DB_PATH", db_file)
    monkeypatch.setattr("src.config.MEMORY_PATH", mem_file)
    init_db(db_file)
    return {"db": db_file, "mem": mem_file}

def test_e2e_full_conversation_and_memory_sync(temp_db):
    db_path = temp_db["db"]
    mem_path = temp_db["mem"]

    # 1. Add semantic fact
    add_semantic_fact("user_preference", "User prefers dark mode UI and Python", db_path=db_path, memory_path=mem_path)

    # 2. Invoke multi-turn conversation
    input_state = {
        "messages": [HumanMessage(content="Remember that my name is Sam and I prefer morning meetings")],
        "session_id": "e2e_session_01",
        "summary": "",
        "token_count": 0,
        "retrieval_triggered": False,
        "retrieved_memories": [],
        "pending_approval_id": None,
        "approval_status": None
    }

    result = agent_app.invoke(input_state)
    assert result["retrieval_triggered"] is True
    assert len(result["messages"]) >= 2

    # 3. Verify MEMORY.md synced file content
    mem_content = mem_path.read_text(encoding="utf-8")
    assert "dark mode" in mem_content or "Sam" in mem_content

def test_e2e_sub_agent_delegation(temp_db):
    tool_output = spawn_agent.invoke({
        "role": "DataResearcher",
        "instructions": "Investigate Python 3.12 GIL performance updates"
    })

    assert "[Sub-Agent 'DataResearcher'" in tool_output
    assert "Status: COMPLETED" in tool_output

def test_e2e_personal_os_and_mcp_tools(temp_db):
    # Personal OS task creation
    task_res = create_task.invoke({"title": "Deploy API", "priority": "High"})
    assert "[Personal OS Task Created]" in task_res

    # Concurrency lock
    lock_res = lock_resource.invoke({"resource_uri": "file:///d:/agent/state.db"})
    assert "locked successfully" in lock_res

    unlock_res = unlock_resource.invoke({"resource_uri": "file:///d:/agent/state.db"})
    assert "unlocked successfully" in unlock_res

    # Event publishing
    pub_res = publish_event.invoke({"topic": "deploy.started", "payload": "v1.0.0"})
    assert "published to topic 'deploy.started'" in pub_res

    # Provider-managed search MCP is unavailable unless configured.
    search_res = search_web.invoke({"query": "LangGraph tutorial"})
    assert "Unavailable" in search_res

def test_e2e_hitl_approval_pause_and_resume(temp_db):
    db_path = temp_db["db"]

    from src.harness.graph import node_hitl_check

    state = {
        "messages": [
            HumanMessage(content="Please delegate this safely"),
            AIMessage(
                content="I need approval to spawn a sub-agent.",
                tool_calls=[{
                    "name": "spawn_agent",
                    "args": {"role": "Researcher", "instructions": "Summarize release risks"},
                    "id": "call_spawn_e2e",
                }],
            ),
        ],
        "session_id": "e2e_hitl_sess",
        "loop_events": [],
    }

    result = node_hitl_check(state)
    assert result["approval_status"] == "PENDING"
    req_id = result["pending_approval_id"]
    assert req_id is not None

    pending_list = get_pending_approvals("e2e_hitl_sess", db_path=db_path)
    assert len(pending_list) == 1
    assert pending_list[0]["tool_name"] == "spawn_agent"

    resume_res = resume_graph_after_approval(req_id, "APPROVED")
    assert resume_res["status"] == "APPROVED"
    assert "Approval GRANTED" in resume_res["message"]

