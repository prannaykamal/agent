import pytest
from fastapi.testclient import TestClient
from src.db import init_db, get_connection
from src.harness.graph import agent_app, log_loop_event
from src.api.server import app
from langchain_core.messages import HumanMessage

@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_loop.db"
    mem_file = tmp_path / "MEMORY.md"

    monkeypatch.setattr("src.db.DB_PATH", db_file)
    monkeypatch.setattr("src.config.MEMORY_PATH", mem_file)
    init_db(db_file)
    return db_file

client = TestClient(app)

def test_loop_event_logging(temp_db):
    evt = log_loop_event(
        session_id="sess_loop_test",
        step_index=1,
        step_type="TOOL_EXECUTION",
        reasoning="Executing test tool",
        tool_name="heartbeat",
        tool_args={},
        tool_result="Personal OS online"
    )

    assert evt["id"].startswith("evt_")
    assert evt["tool_name"] == "heartbeat"

    conn = get_connection(temp_db)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM loop_events WHERE session_id = 'sess_loop_test'")
    rows = cursor.fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0]["tool_name"] == "heartbeat"

def test_agent_graph_loop_execution(temp_db):
    input_state = {
        "messages": [HumanMessage(content="Check system heartbeat")],
        "session_id": "sess_graph_loop",
        "summary": "",
        "token_count": 0,
        "retrieval_triggered": False,
        "retrieved_memories": [],
        "pending_approval_id": None,
        "approval_status": None,
        "provider": "openai",
        "model_name": "gpt-4o-mini"
    }

    res = agent_app.invoke(input_state)
    assert "messages" in res
    assert res.get("loop_count", 0) >= 1
    assert "loop_events" in res

def test_api_chat_loop_metadata(temp_db):
    response = client.post(
        "/api/chat",
        json={
            "message": "Check tools status",
            "session_id": "sess_api_loop",
            "provider": "openai",
            "model_name": "gpt-4o-mini"
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert "response" in data
    assert "iterations" in data
    assert "tools_used" in data
    assert "loop_events" in data
    assert data["iterations"] >= 1
