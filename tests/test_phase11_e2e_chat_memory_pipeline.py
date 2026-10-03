import sqlite3

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import HumanMessage, SystemMessage

from src.api.server import app
from src.db import init_db
from src.harness.graph import node_memory_router
from src.memory.cognee_memory import get_cognee_memory

client = TestClient(app)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "phase11_chat.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file


def _count(db_path, table):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def _memory_blocks(messages):
    return [
        message
        for message in messages
        if isinstance(message, SystemMessage) and str(message.content).startswith("[Retrieved Long-Term Memory]")
    ]


def test_normal_chat_with_no_memory_keeps_api_shape_and_enqueues_only(temp_db):
    response = client.post(
        "/api/chat",
        json={"message": "Hello assistant", "session_id": "phase11-chat", "provider": "openai", "model_name": "gpt-4o-mini"},
    )

    assert response.status_code == 200
    data = response.json()
    assert {
        "session_id",
        "session_title",
        "response",
        "retrieval_triggered",
        "retrieved_memories",
        "pending_approval_id",
        "approval_status",
        "iterations",
        "tools_used",
        "loop_events",
        "loop_trace",
    } <= set(data)
    assert _count(temp_db, "worker_heartbeats") == 0


def _teach(*documents):
    get_cognee_memory().remember_permanent(list(documents))


@pytest.fixture
def retrieving_jev(fake_jev):
    fake_jev.memory = {"should_store": False, "should_retrieve": True}
    return fake_jev


def test_chat_retrieval_injects_one_cognee_block_and_writes_nothing(temp_db, fake_cognee, retrieving_jev):
    _teach(
        "Fact about the user (profile): User prefers pytest and deployment checklists",
        "Past episode: we decided to keep pytest smoke checks in the deployment checklist.",
        "Procedure: Deploy Checklist\nSteps: run pytest, deploy, smoke test.",
    )

    text = "what do you remember about my deployment pytest checklist?"
    before = (_count(temp_db, "memory_jobs"), len(fake_cognee.remember_calls), len(fake_cognee.improve_calls))
    result = node_memory_router({"messages": [HumanMessage(content=text)], "session_id": "phase11-retrieval"})
    after = (_count(temp_db, "memory_jobs"), len(fake_cognee.remember_calls), len(fake_cognee.improve_calls))

    blocks = _memory_blocks(result["messages"])
    assert result["retrieval_triggered"] is True
    assert len(blocks) == 1
    assert "deployment checklists" in blocks[0].content
    assert "Deploy Checklist" in blocks[0].content
    assert len(result["retrieved_memories"]) == 3
    assert all(item["kind"] == "long_term" for item in result["retrieved_memories"])
    assert sum(1 for message in result["messages"] if isinstance(message, HumanMessage) and message.content == text) == 1
    # Retrieval is read-only and asks cognee for context, not a generated answer.
    assert after == before
    assert fake_cognee.search_calls[-1]["only_context"] is True
    assert fake_cognee.search_calls[-1]["datasets"] == ["ivo_memory"]


def test_retrieval_respects_token_budget(temp_db, fake_cognee, retrieving_jev):
    _teach("checklist " + "word " * 5000)

    result = node_memory_router({"messages": [HumanMessage(content="show the checklist")], "session_id": "phase11"})

    [block] = _memory_blocks(result["messages"])
    assert len(block.content) // 4 <= get_cognee_memory().config.retrieval_token_budget + 20


def test_greeting_and_math_retrieval_skips(temp_db, fake_cognee, retrieving_jev):
    greeting = node_memory_router({"messages": [HumanMessage(content="hello")], "session_id": "phase11"})
    math = node_memory_router({"messages": [HumanMessage(content="2 + 2")], "session_id": "phase11"})

    assert greeting["retrieval_triggered"] is False
    assert math["retrieval_triggered"] is False
    assert _memory_blocks(greeting["messages"]) == []
    assert _memory_blocks(math["messages"]) == []
    assert retrieving_jev.calls == []


def test_empty_graph_does_not_inject_a_block(temp_db, fake_cognee, retrieving_jev):
    result = node_memory_router({"messages": [HumanMessage(content="what is my favourite editor?")], "session_id": "phase11"})

    assert result["retrieval_triggered"] is False
    assert _memory_blocks(result["messages"]) == []


def test_cognee_failure_does_not_fail_chat(temp_db, fake_cognee, retrieving_jev, monkeypatch):
    async def explode(**kwargs):
        raise RuntimeError("graph database offline")

    monkeypatch.setattr(fake_cognee, "search", explode)

    result = node_memory_router({"messages": [HumanMessage(content="what is my deploy preference?")], "session_id": "phase11"})

    assert result["retrieval_triggered"] is False
    assert _memory_blocks(result["messages"]) == []


def test_disabled_cognee_skips_retrieval_without_error(temp_db):
    result = node_memory_router({"messages": [HumanMessage(content="what is my deploy preference?")], "session_id": "phase11"})

    assert result["retrieval_triggered"] is False


def test_chat_path_does_not_resolve_secondary_route(temp_db, monkeypatch):
    def fail_secondary(*args, **kwargs):
        raise AssertionError("chat path must not resolve secondary LLM")

    monkeypatch.setattr("src.harness.llm_router.resolve_secondary_llm", fail_secondary)
    monkeypatch.setattr("src.harness.llm_router.resolve_secondary_from_job_payload", fail_secondary)

    response = client.post(
        "/api/chat",
        json={"message": "Hello without secondary", "session_id": "phase11-no-secondary", "provider": "openai", "model_name": "gpt-4o-mini"},
    )

    assert response.status_code == 200
