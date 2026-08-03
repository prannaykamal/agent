import pytest
import sqlite3
from pathlib import Path
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from src.db import init_db, add_fact, query_facts_fts
from src.memory.episodic import log_episode
from src.memory.soul_loader import load_soul_prompt

from src.memory.short_term import manage_short_term_memory
from src.harness.graph import agent_app

@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_state.db"
    init_db(db_file)
    return db_file

def test_db_initialization_and_fts5(temp_db):
    # Verify tables created
    conn = sqlite3.connect(str(temp_db))
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [row[0] for row in cursor.fetchall()]
    conn.close()

    assert "episodes" in tables
    assert "facts" in tables
    assert "skills" in tables
    assert "checkpoints" in tables

    # Test FTS5 insertion and search
    add_fact(category="preference", fact_text="User prefers dark mode UI", db_path=temp_db)
    results = query_facts_fts(query="dark mode", db_path=temp_db)
    assert len(results) >= 1
    assert "dark mode" in results[0]["fact_text"]

def test_soul_loader(tmp_path):
    soul_file = tmp_path / "SOUL.md"
    soul_file.write_text("# Master Prompt\nYou are test assistant.", encoding="utf-8")
    
    sys_msg = load_soul_prompt(soul_file)
    assert isinstance(sys_msg, SystemMessage)
    assert "You are test assistant" in sys_msg.content

def test_short_term_memory_compatibility_wrapper_does_not_trim_by_message_count():
    sys_msg = SystemMessage(content="System prompt")
    messages = [sys_msg]

    for i in range(15):
        messages.append(HumanMessage(content=f"Message {i}"))
        messages.append(AIMessage(content=f"Response {i}"))

    returned_messages, summary = manage_short_term_memory(messages, max_messages=10)

    assert returned_messages is messages
    assert len(returned_messages) == len(messages)
    assert summary == ""
    assert not any("[Context Summary]" in m.content for m in returned_messages if isinstance(m, SystemMessage))

def test_langgraph_agent_invocation(temp_db, monkeypatch):
    # Set DB_PATH for the test
    monkeypatch.setattr("src.harness.graph.log_episode", lambda session_id, content: log_episode(session_id, content, db_path=temp_db))

    
    input_state = {
        "messages": [HumanMessage(content="Hello assistant!")],
        "session_id": "test_session_001",
        "summary": "",
        "token_count": 0
    }
    
    output_state = agent_app.invoke(input_state)
    assert "messages" in output_state
    assert len(output_state["messages"]) >= 2  # System + User + AI
    last_msg = output_state["messages"][-1]
    assert isinstance(last_msg, AIMessage)
    assert len(last_msg.content) > 0
