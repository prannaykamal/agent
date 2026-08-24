import pytest
import sqlite3
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from src.db import init_db, add_fact, query_facts_fts
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


def test_normalize_llm_messages_moves_trailing_system_to_front():
    from src.harness.graph import _normalize_llm_messages

    normalized = _normalize_llm_messages(
        [
            SystemMessage(content="You are Ivo."),
            HumanMessage(content="send mail to a@gmail.com saying hi"),
            SystemMessage(content="[Retrieved Long-Term Memory]\n- fact"),
        ]
    )
    assert [type(message).__name__ for message in normalized] == ["SystemMessage", "HumanMessage"]
    assert "You are Ivo." in normalized[0].content
    assert "[Retrieved Long-Term Memory]" in normalized[0].content
    assert normalized[1].content == "send mail to a@gmail.com saying hi"


def test_sanitize_drops_orphan_tool_messages():
    from langchain_core.messages import ToolMessage
    from src.harness.graph import _sanitize_llm_messages

    sanitized = _sanitize_llm_messages(
        [
            SystemMessage(content="You are Ivo."),
            HumanMessage(content="yes"),
            AIMessage(content="[HUMAN APPROVAL REQUIRED]"),
            ToolMessage(content="Sent.", tool_call_id="call_1", name="email_send"),
        ]
    )
    assert [type(message).__name__ for message in sanitized] == ["SystemMessage", "HumanMessage", "AIMessage"]
    assert not any(type(message).__name__ == "ToolMessage" for message in sanitized)


def test_sanitize_keeps_paired_tool_results():
    from langchain_core.messages import ToolMessage
    from src.harness.graph import _sanitize_llm_messages

    assistant = AIMessage(
        content="",
        tool_calls=[{"name": "email_draft", "args": {"to": "a@x.com"}, "id": "call_1"}],
    )
    sanitized = _sanitize_llm_messages(
        [
            HumanMessage(content="draft it"),
            assistant,
            ToolMessage(content="Draft created", tool_call_id="call_1", name="email_draft"),
        ]
    )
    assert sanitized[-1].content == "Draft created"
    assert sanitized[-2].tool_calls[0]["id"] == "call_1"


def test_sanitize_strips_unpaired_tool_calls():
    from src.harness.graph import _sanitize_llm_messages

    sanitized = _sanitize_llm_messages(
        [
            HumanMessage(content="send it"),
            AIMessage(
                content="",
                tool_calls=[{"name": "email_send", "args": {"to": "a@x.com"}, "id": "call_1"}],
            ),
            AIMessage(content="[HUMAN APPROVAL REQUIRED]"),
        ]
    )
    assert [type(message).__name__ for message in sanitized] == ["HumanMessage", "AIMessage", "AIMessage"]
    assert not getattr(sanitized[1], "tool_calls", None)


def test_resume_user_response_ignores_approval_stall():
    from src.harness.graph import _resume_user_response

    stall = AIMessage(content="I attempted to send the email, but it requires additional approval due to safety protocols.")
    assert _resume_user_response([stall], "Sent Gmail message 19ff to a@x.com.") == "Sent Gmail message 19ff to a@x.com."
    assert _resume_user_response([AIMessage(content="Email sent to a@x.com.")], "Sent.") == "Email sent to a@x.com."


def test_langgraph_agent_invocation(temp_db):
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
