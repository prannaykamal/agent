import sqlite3

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import HumanMessage, SystemMessage

from src.api.server import app
from src.db import add_fact, init_db
from src.harness.graph import node_retrieval_gate
from src.memory.episode_store import StructuredEpisodeRepository, StructuredEpisodeWrite
from src.memory.skill_store import SkillVersionStore, SkillVersionWrite
from src.memory.summary_blocks import SummaryBlockRepository

client = TestClient(app)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "phase11_chat.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    monkeypatch.setattr("src.config.MEMORY_PATH", tmp_path / "MEMORY.md")
    monkeypatch.setattr("src.config.SKILL_PATH", tmp_path / "SKILL.md")
    monkeypatch.setattr("src.memory.skill_files.SKILL_PATH", tmp_path / "SKILL.md")
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


def test_chat_with_all_memory_kinds_appends_one_block_and_current_user_once(temp_db, tmp_path):
    session_id = "phase11-retrieval"
    add_fact("profile", "User prefers pytest and deployment checklists", db_path=temp_db)
    SummaryBlockRepository(db_path=temp_db).append_summary_block(
        session_id=session_id,
        summary="The deployment project uses pytest smoke checks.",
        covered_message_ids=["turn-1"],
        start_message_id="turn-1",
        end_message_id="turn-1",
        source_job_id="summary-job",
        token_count=8,
        original_token_count=80,
        model_provider="openai",
        model_name="gpt-4o-mini",
    )
    StructuredEpisodeRepository(db_path=temp_db).append_episode(
        StructuredEpisodeWrite(
            id="episode-phase11",
            session_id=session_id,
            title="Deployment checklist decision",
            summary="We decided to keep pytest smoke checks in the deploy checklist.",
            participants=["User", "Assistant"],
            goals=["Deploy safely"],
            decisions=["Run pytest smoke checks"],
            artifacts=["deploy-checklist.md"],
            topics=["deployment", "pytest"],
            importance=0.9,
            start_message_id="turn-1",
            end_message_id="turn-2",
            source="test",
            source_job_id="episode-job",
        )
    )
    SkillVersionStore(db_path=temp_db, skill_path=tmp_path / "SKILL.md").create_version(
        SkillVersionWrite(
            name="Deploy Checklist",
            description="Run deployment checklist steps.",
            trigger_keywords="deploy, checklist, pytest",
            execution_steps="1. Run pytest. 2. Deploy. 3. Smoke test.",
            preferred_tools=["shell"],
            tags=["deployment"],
        )
    )

    text = "what do you remember about my deployment pytest checklist?"
    before = {table: _count(temp_db, table) for table in ["memory_jobs", "semantic_embeddings", "semantic_dedup_events", "skill_usage_stats"]}
    result = node_retrieval_gate({"messages": [HumanMessage(content=text)], "session_id": session_id})
    after = {table: _count(temp_db, table) for table in before}

    blocks = _memory_blocks(result["messages"])
    assert result["retrieval_triggered"] is True
    assert len(blocks) == 1
    assert "[Retrieved Long-Term Memory]" in blocks[0].content
    assert any(label in blocks[0].content for label in ["Semantic Facts:", "Past Episodes:", "Procedural Skills:", "Conversation Summaries:"])
    assert sum(1 for message in result["messages"] if isinstance(message, HumanMessage) and message.content == text) == 1
    assert after == before


def test_greeting_and_math_retrieval_skips(temp_db):
    greeting = node_retrieval_gate({"messages": [HumanMessage(content="hello")], "session_id": "phase11"})
    math = node_retrieval_gate({"messages": [HumanMessage(content="2 + 2")], "session_id": "phase11"})

    assert greeting["retrieval_triggered"] is False
    assert math["retrieval_triggered"] is False
    assert _memory_blocks(greeting["messages"]) == []
    assert _memory_blocks(math["messages"]) == []


def test_retrieval_source_failure_is_isolated(temp_db, monkeypatch):
    add_fact("profile", "User prefers resilient retrieval", db_path=temp_db)

    def fail_summary(self, request):
        raise RuntimeError("summary source down")

    monkeypatch.setattr("src.memory.retrieval_sources.SummaryBlockRetrievalSource.retrieve", fail_summary)

    result = node_retrieval_gate({"messages": [HumanMessage(content="what is my resilient retrieval preference?")], "session_id": "phase11"})

    assert result["retrieval_triggered"] is True
    assert len(_memory_blocks(result["messages"])) == 1
    assert "resilient retrieval" in _memory_blocks(result["messages"])[0].content


def test_global_retrieval_failure_falls_back_without_failing_chat(temp_db, monkeypatch):
    add_fact("profile", "User prefers legacy fallback safety", db_path=temp_db)

    def explode(*args, **kwargs):
        raise RuntimeError("planner failed globally")

    monkeypatch.setattr("src.harness.graph.build_retrieval_plan", explode)

    result = node_retrieval_gate({"messages": [HumanMessage(content="what is my legacy fallback preference?")], "session_id": "phase11"})

    assert result["retrieval_triggered"] is True
    assert len(_memory_blocks(result["messages"])) <= 1


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
