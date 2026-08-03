import pytest
from pathlib import Path
from src.db import init_db
from src.orchestration.registry import register_sub_agent, update_sub_agent_status, get_sub_agent, list_sub_agents
from src.orchestration.sub_agent import execute_sub_agent
from src.orchestration.tools import spawn_agent

@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_orchestration.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file

def test_sub_agent_registry(temp_db):
    agent_id = "sub_001"
    register_sub_agent(agent_id, "parent_100", "DataAnalyst", "Analyze quarterly numbers", db_path=temp_db)

    record = get_sub_agent(agent_id, db_path=temp_db)
    assert record is not None
    assert record["role"] == "DataAnalyst"
    assert record["status"] == "RUNNING"

    update_sub_agent_status(agent_id, "COMPLETED", "Analysis complete", db_path=temp_db)
    updated_record = get_sub_agent(agent_id, db_path=temp_db)
    assert updated_record["status"] == "COMPLETED"
    assert updated_record["result"] == "Analysis complete"

    agents_list = list_sub_agents("parent_100", db_path=temp_db)
    assert len(agents_list) == 1
    assert agents_list[0]["agent_id"] == agent_id

def test_execute_sub_agent_isolation(temp_db):
    res = execute_sub_agent(
        role="CodeInspector",
        instructions="Check python code style",
        parent_session_id="session_test",
        db_path=temp_db
    )

    assert res["status"] == "COMPLETED"
    assert res["role"] == "CodeInspector"
    assert "sub_agent_" in res["agent_id"]

    db_rec = get_sub_agent(res["agent_id"], db_path=temp_db)
    assert db_rec is not None
    assert db_rec["status"] == "COMPLETED"

def test_spawn_agent_tool(temp_db, monkeypatch):
    monkeypatch.setattr(
        "src.orchestration.tools.execute_sub_agent",
        lambda role, instructions: execute_sub_agent(role, instructions, db_path=temp_db)
    )

    tool_output = spawn_agent.invoke({"role": "Summarizer", "instructions": "Summarize latest email thread"})
    assert "[Sub-Agent 'Summarizer'" in tool_output
    assert "Status: COMPLETED" in tool_output
