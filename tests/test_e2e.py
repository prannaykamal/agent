import pytest
from pathlib import Path
from langchain_core.messages import HumanMessage, AIMessage

from src.db import init_db
from datetime import datetime, timedelta, timezone

from src.memory.cognee_memory import get_cognee_memory
from src.memory.worker import process_one_memory_job
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

def test_e2e_conversation_is_remembered_through_cognee(temp_db, fake_cognee, fake_jev, stub_primary_llm, monkeypatch):
    db_path = temp_db["db"]
    memory = get_cognee_memory()
    memory.remember_permanent(["Fact about the user (user_preference): User prefers dark mode UI and Python"])

    # 1. Jev asks for retrieval and storage: chat recalls the existing fact.
    fake_jev.memory = {"should_store": True, "should_retrieve": True}
    input_state = {
        "messages": [HumanMessage(content="Remember that my name is Sam and I prefer morning meetings with Python demos")],
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
    assert result["memory_storage_decision"]["should_store"] is True
    assert len(result["messages"]) >= 2

    # 2. The worker writes the turn into the session graph; the merge waits for idle.
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    monkeypatch.setattr("src.memory.job_handlers._utcnow", lambda: now)
    write = process_one_memory_job("e2e-worker", db_path=db_path, now=now)
    assert (write.job_type, write.status) == ("memory_session_write", "SUCCEEDED")
    assert memory.recall("When does Sam prefer meetings?").memories == []

    # 3. After the idle timeout the session merges into the main graph and becomes recallable.
    later = now + timedelta(minutes=31)
    monkeypatch.setattr("src.memory.job_handlers._utcnow", lambda: later)
    merge = process_one_memory_job("e2e-worker", db_path=db_path, now=later)
    assert (merge.job_type, merge.status) == ("memory_session_merge", "SUCCEEDED")
    recalled = memory.recall("When does Sam prefer meetings?")
    assert any("morning meetings" in item.content for item in recalled.memories)

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

