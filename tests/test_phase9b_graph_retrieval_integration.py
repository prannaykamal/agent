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


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "phase9b_graph.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file


def _memory_blocks(messages):
    return [
        message
        for message in messages
        if isinstance(message, SystemMessage) and str(message.content).startswith("[Retrieved Long-Term Memory]")
    ]


def test_greeting_and_math_graph_retrieval_skip(temp_db):
    greeting = node_retrieval_gate({"messages": [HumanMessage(content="hello")], "session_id": "sess"})
    math = node_retrieval_gate({"messages": [HumanMessage(content="2 + 2")], "session_id": "sess"})

    assert greeting["retrieval_triggered"] is False
    assert math["retrieval_triggered"] is False
    assert _memory_blocks(greeting["messages"]) == []
    assert _memory_blocks(math["messages"]) == []


def test_semantic_fact_query_appends_one_memory_system_message(temp_db):
    add_fact("profile", "User prefers FastAPI for backend services", db_path=temp_db)

    result = node_retrieval_gate(
        {"messages": [HumanMessage(content="what is my FastAPI preference?")], "session_id": "sess"}
    )

    blocks = _memory_blocks(result["messages"])
    assert result["retrieval_triggered"] is True
    assert len(blocks) == 1
    assert "Semantic Facts:" in blocks[0].content
    assert "User prefers FastAPI" in blocks[0].content
    assert result["retrieved_memories"][0]["memory_kind"] == "semantic"


def test_structured_episode_retrieval_is_used(temp_db, monkeypatch):
    def fail_legacy(*args, **kwargs):
        raise AssertionError("legacy episode search should not be used when new retrieval succeeds")

    monkeypatch.setattr("src.harness.graph.search_episodes_fts", fail_legacy)
    StructuredEpisodeRepository(db_path=temp_db).append_episode(
        StructuredEpisodeWrite(
            id="episode-1",
            session_id="sess",
            title="Staging decision",
            summary="We decided to run smoke tests after deployment.",
            participants=["User", "Assistant"],
            goals=["Deploy safely"],
            decisions=["Run smoke tests"],
            artifacts=["deploy-checklist.md"],
            topics=["staging", "deployment"],
            importance=0.9,
            start_message_id="turn-1",
            end_message_id="turn-3",
            source="test",
            source_job_id="episode-job-1",
        )
    )

    result = node_retrieval_gate(
        {"messages": [HumanMessage(content="what did we decide last time about staging?")], "session_id": "sess"}
    )

    block = _memory_blocks(result["messages"])[0]
    assert "Past Episodes:" in block.content
    assert "Staging decision" in block.content


def test_approved_procedural_skill_can_appear(temp_db, tmp_path, monkeypatch):
    def fail_record_used(*args, **kwargs):
        raise AssertionError("retrieval must not increment usage stats")

    monkeypatch.setattr("src.memory.skill_store.SkillVersionStore.record_used", fail_record_used)
    SkillVersionStore(db_path=temp_db, skill_path=tmp_path / "SKILL.md").create_version(
        SkillVersionWrite(
            name="Deploy Staging",
            description="Deploys the app to staging.",
            trigger_keywords="deploy, staging",
            execution_steps="1. Build. 2. Deploy. 3. Smoke test.",
            preferred_tools=["shell"],
            tags=["deployment"],
        )
    )

    result = node_retrieval_gate(
        {"messages": [HumanMessage(content="how do I deploy staging?")], "session_id": "sess"}
    )

    block = _memory_blocks(result["messages"])[0]
    assert "Procedural Skills:" in block.content
    assert "Deploy Staging" in block.content


def test_summary_block_can_appear(temp_db):
    SummaryBlockRepository(db_path=temp_db).append_summary_block(
        session_id="sess",
        summary="The project is implementing adaptive retrieval planning.",
        covered_message_ids=["turn-1", "turn-2"],
        start_message_id="turn-1",
        end_message_id="turn-2",
        source_job_id="summary-job-1",
        token_count=10,
        original_token_count=100,
        model_provider="openai",
        model_name="gpt-4o-mini",
    )

    result = node_retrieval_gate(
        {"messages": [HumanMessage(content="catch me up with the project context")], "session_id": "sess"}
    )

    block = _memory_blocks(result["messages"])[0]
    assert "Conversation Summaries:" in block.content
    assert "adaptive retrieval planning" in block.content


def test_current_user_message_remains_exactly_once(temp_db):
    add_fact("profile", "User prefers pytest", db_path=temp_db)
    text = "what is my pytest preference?"

    result = node_retrieval_gate({"messages": [HumanMessage(content=text)], "session_id": "sess"})

    assert sum(1 for message in result["messages"] if isinstance(message, HumanMessage) and message.content == text) == 1
    assert len(_memory_blocks(result["messages"])) == 1


def test_api_chat_response_shape_unchanged(temp_db):
    client = TestClient(app)

    response = client.post(
        "/api/chat",
        json={"message": "Hello assistant", "session_id": "phase9b-api", "provider": "openai", "model_name": "gpt-4o-mini"},
    )

    assert response.status_code == 200
    data = response.json()
    assert set(data) >= {"response", "session_id"}
    assert data["session_id"] == "phase9b-api"


def test_retrieval_path_does_not_write_embeddings_or_dedup_events(temp_db, monkeypatch):
    add_fact("profile", "User prefers pytest", db_path=temp_db)

    def fail_upsert(*args, **kwargs):
        raise AssertionError("retrieval must not upsert embeddings")

    monkeypatch.setattr("src.memory.embeddings.SemanticEmbeddingStore.upsert_embedding", fail_upsert)
    before = sqlite3.connect(temp_db)
    try:
        before_dedup = before.execute("SELECT COUNT(*) FROM semantic_dedup_events").fetchone()[0]
        before_embeddings = before.execute("SELECT COUNT(*) FROM semantic_embeddings").fetchone()[0]
    finally:
        before.close()

    result = node_retrieval_gate({"messages": [HumanMessage(content="what is my pytest preference?")], "session_id": "sess"})

    conn = sqlite3.connect(temp_db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM semantic_dedup_events").fetchone()[0] == before_dedup
        assert conn.execute("SELECT COUNT(*) FROM semantic_embeddings").fetchone()[0] == before_embeddings
    finally:
        conn.close()
    assert result["retrieval_triggered"] is True


def test_named_fact_is_retrieved_in_a_new_session(temp_db):
    add_fact("user_fact", "Prannay's email is prannay@kamal.dev", db_path=temp_db)

    result = node_retrieval_gate(
        {
            "messages": [HumanMessage(content="send 5 mails to Prannay saying hi in Spanish")],
            "session_id": "brand_new_session",
        }
    )

    blocks = _memory_blocks(result["messages"])
    assert result["retrieval_triggered"] is True
    assert blocks
    assert "prannay@kamal.dev" in blocks[0].content


def test_ingest_persists_explicit_facts_for_later_chats(temp_db, tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.MEMORY_PATH", tmp_path / "MEMORY.md")
    from src.harness.graph import node_ingest

    node_ingest(
        {
            "messages": [HumanMessage(content="Priya's timezone is IST. Remember that staging VPN needs approval.")],
            "session_id": "chat_one",
        }
    )

    result = node_retrieval_gate(
        {
            "messages": [HumanMessage(content="what is Priya's timezone, and does staging VPN need approval?")],
            "session_id": "chat_two",
        }
    )

    blocks = _memory_blocks(result["messages"])
    assert result["retrieval_triggered"] is True
    assert blocks
    content = blocks[0].content
    assert "IST" in content
    assert "staging VPN needs approval" in content
