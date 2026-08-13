import sqlite3

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from src.db import add_fact, init_db
from src.harness.graph import node_retrieval_gate
from src.memory.durable_facts import promote_durable_candidates
from src.memory.entity_index import EntityIndexStore, extract_query_entities
from src.memory.profile_pin import PINNED_PROFILE_HEADER, assemble_pinned_profile
from src.memory.retrieval_planner import build_retrieval_plan, classify_retrieval_task
from src.memory.retrieval_ranker import reciprocal_rank_fusion
from src.memory.retrieval_sources import retrieve_semantic_facts
from src.memory.retrieval_types import RetrievalRequest
from src.memory.semantic_candidates import PendingFactCandidateRecord


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "retrieval_system.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    monkeypatch.setattr("src.config.MEMORY_PATH", tmp_path / "MEMORY.md")
    init_db(db_file)
    return db_file


def _count(db_path, table):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def _retrieved_blocks(messages):
    return [
        message
        for message in messages
        if isinstance(message, SystemMessage) and str(message.content).startswith("[Retrieved Long-Term Memory]")
    ]


def _pinned_blocks(messages):
    return [
        message
        for message in messages
        if isinstance(message, SystemMessage) and str(message.content).startswith(PINNED_PROFILE_HEADER)
    ]


def test_entity_index_is_written_on_add_fact(temp_db):
    add_fact("user_fact", "Priya's timezone is IST", db_path=temp_db)

    ids = EntityIndexStore(db_path=temp_db).lookup_fact_ids(["priya"], limit=5)

    assert ids
    assert _count(temp_db, "memory_entities") > 0


def test_named_timezone_is_retrieved_in_a_new_session(temp_db):
    add_fact("user_fact", "Priya's timezone is IST", db_path=temp_db)

    result = node_retrieval_gate(
        {
            "messages": [HumanMessage(content="what timezone is Priya in?")],
            "session_id": "later_chat",
        }
    )

    blocks = _retrieved_blocks(result["messages"])
    assert result["retrieval_triggered"] is True
    assert blocks
    assert "IST" in blocks[0].content
    assert "Priya" in blocks[0].content


def test_named_contact_is_retrieved_for_an_action_request(temp_db):
    add_fact("user_fact", "Alex's email is alex@example.org", db_path=temp_db)

    result = node_retrieval_gate(
        {
            "messages": [HumanMessage(content="draft a message to Alex about the launch")],
            "session_id": "brand_new_session",
        }
    )

    combined = "\n".join(message.content for message in result["messages"] if isinstance(message, SystemMessage))
    assert "alex@example.org" in combined
    assert "example.com" not in combined


def test_preference_paraphrase_retrieves_stored_fact(temp_db):
    add_fact("user_preference", "User prefers pytest for running tests", db_path=temp_db)

    result = retrieve_semantic_facts(
        RetrievalRequest(query="how should I run tests?", per_source_limit=3),
        db_path=temp_db,
    )

    assert result.candidates
    assert "pytest" in result.candidates[0].content


def test_greeting_skips_retrieval_and_pin(temp_db):
    add_fact("user_profile", "User name is Khusham", db_path=temp_db)

    result = node_retrieval_gate({"messages": [HumanMessage(content="hello")], "session_id": "sess"})

    assert result["retrieval_triggered"] is False
    assert _retrieved_blocks(result["messages"]) == []
    assert _pinned_blocks(result["messages"]) == []


def test_unrelated_office_fact_is_not_retrieved_on_thanks(temp_db):
    add_fact("user_fact", "The office address is 10 Market Street", db_path=temp_db)

    result = node_retrieval_gate({"messages": [HumanMessage(content="thanks")], "session_id": "sess"})
    semantic = retrieve_semantic_facts(
        RetrievalRequest(query="2 + 2", per_source_limit=3, task_type="broad_memory"),
        db_path=temp_db,
    )

    assert result["retrieval_triggered"] is False
    assert semantic.candidates == tuple()


def test_pinned_profile_is_separate_from_retrieved_block(temp_db):
    add_fact("user_profile", "User name is Khusham", db_path=temp_db)
    add_fact("user_fact", "Priya's timezone is IST", db_path=temp_db)

    result = node_retrieval_gate(
        {
            "messages": [HumanMessage(content="what timezone is Priya in?")],
            "session_id": "sess",
        }
    )

    assert len(_pinned_blocks(result["messages"])) == 1
    assert len(_retrieved_blocks(result["messages"])) == 1
    assert "Khusham" in _pinned_blocks(result["messages"])[0].content


def test_entity_weighted_plan_keeps_broad_task_type(temp_db, monkeypatch):
    add_fact("user_fact", "Priya's timezone is IST", db_path=temp_db)

    from tests.test_phase9b_retrieval_planner import FakeBudget

    monkeypatch.setattr(
        "src.memory.retrieval_planner.calculate_budget_for_primary_route",
        lambda **kwargs: FakeBudget(),
    )

    query = "draft a note for Priya"
    assert classify_retrieval_task(query) == "broad_memory"
    plan = build_retrieval_plan(
        query=query,
        session_id="sess",
        provider="openai",
        model_name="gpt-4o-mini",
        messages=[HumanMessage(content=query)],
        gate_allows_retrieval=True,
        db_path=temp_db,
    )

    assert plan.task_type == "broad_memory"
    assert plan.memory_kinds[0] == "semantic"
    assert plan.budget_by_kind["semantic"] >= plan.budget_by_kind.get("episodic", 0)


def test_worker_promoted_durable_fact_is_retrievable(temp_db):
    candidate = PendingFactCandidateRecord(
        id="cand-durable-1",
        session_id="sess",
        source_message_id="turn-1",
        source_episode_id=None,
        fact="Jordan's office is in Berlin",
        category="user_fact",
        confidence=0.91,
        explicit=False,
        source="secondary_llm",
        status="PENDING",
        batch_id=None,
        metadata={"durable": True},
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        processed_at=None,
    )

    promoted = promote_durable_candidates([candidate], db_path=temp_db)
    result = retrieve_semantic_facts(
        RetrievalRequest(query="where is Jordan's office?", per_source_limit=3),
        db_path=temp_db,
    )

    assert promoted == 1
    assert result.candidates
    assert "Berlin" in result.candidates[0].content


def test_retrieval_does_not_upsert_embeddings(temp_db, monkeypatch):
    add_fact("user_fact", "Sam's nickname is Skip", db_path=temp_db)

    def fail_upsert(*args, **kwargs):
        raise AssertionError("retrieval must not upsert embeddings")

    monkeypatch.setattr("src.memory.embeddings.SemanticEmbeddingStore.upsert_embedding", fail_upsert)
    before = _count(temp_db, "semantic_embeddings")

    retrieve_semantic_facts(RetrievalRequest(query="what is Sam's nickname?"), db_path=temp_db)
    node_retrieval_gate({"messages": [HumanMessage(content="what is Sam's nickname?")], "session_id": "other"})

    assert _count(temp_db, "semantic_embeddings") == before


def test_reciprocal_rank_fusion_prefers_shared_top_hits():
    fused = reciprocal_rank_fusion((["a", "b", "c"], ["c", "a", "d"]))

    assert fused["a"] > fused["b"]
    assert fused["a"] > fused["d"]


def test_query_entity_extraction_skips_leading_capital(temp_db):
    entities = extract_query_entities("Send a note to Priya tomorrow")

    assert "priya" in entities
    from src.memory.entity_index import extract_proper_names

    assert "send" not in extract_proper_names("Send a note to Priya tomorrow")
    assert "priya" in extract_proper_names("Send a note to Priya tomorrow")


def test_assemble_pinned_profile_is_capped(temp_db):
    for index in range(20):
        add_fact("user_fact", f"Contact {index}'s desk is floor {index}", db_path=temp_db)

    block = assemble_pinned_profile(db_path=temp_db)

    assert block.startswith(PINNED_PROFILE_HEADER)
    assert block.count("\n- ") <= 12


def test_ingest_timezone_is_retrieved_in_a_later_chat(temp_db):
    from src.memory.semantic import persist_explicit_facts_from_user_text

    written = persist_explicit_facts_from_user_text("Priya's timezone is IST", db_path=temp_db)
    result = node_retrieval_gate(
        {
            "messages": [HumanMessage(content="what timezone is Priya in?")],
            "session_id": "later_chat_after_ingest",
        }
    )
    blocks = _retrieved_blocks(result["messages"])

    assert written == 1
    assert result["retrieval_triggered"] is True
    assert blocks
    assert "IST" in blocks[0].content


def test_lowercase_leading_name_is_indexed_and_retrieved(temp_db):
    from src.memory.entity_index import extract_proper_names, lookup_facts_for_query

    add_fact("user_fact", "prannay is my cofounder", db_path=temp_db)

    assert "prannay" in extract_proper_names("prannay is my cofounder")
    assert "prannay" in extract_proper_names("Prannay is my cofounder")
    assert lookup_facts_for_query("who is Prannay?", db_path=temp_db, limit=5)

    result = node_retrieval_gate(
        {
            "messages": [HumanMessage(content="who is Prannay?")],
            "session_id": "new_chat_lowercase_name",
        }
    )
    combined = "\n".join(message.content for message in result["messages"] if isinstance(message, SystemMessage))

    assert "prannay" in combined.lower()
    assert "cofounder" in combined.lower()


def test_newer_office_location_supersedes_older_in_retrieve_and_pin(temp_db):
    add_fact("user_fact", "The office is in NY", db_path=temp_db)
    add_fact("user_fact", "The office is in SF", db_path=temp_db)

    result = node_retrieval_gate(
        {
            "messages": [HumanMessage(content="where is the office?")],
            "session_id": "new_chat_office_move",
        }
    )
    pin = assemble_pinned_profile(db_path=temp_db)
    retrieved = "\n".join(block.content for block in _retrieved_blocks(result["messages"]))
    combined = "\n".join(
        message.content for message in result["messages"] if isinstance(message, SystemMessage)
    )

    assert _count(temp_db, "facts") == 2
    assert "SF" in retrieved
    assert "NY" not in retrieved
    assert "SF" in pin
    assert "NY" not in pin
    assert "NY" not in combined


def test_hash_embedding_does_not_retrieve_unrelated_fact(temp_db):
    from src.memory.embeddings import EmbeddingInput, SemanticEmbeddingStore, SEMANTIC_FACT_OWNER_TYPE

    fact_text = "User prefers FastAPI for backend services"
    add_fact("user_preference", fact_text, db_path=temp_db)
    conn = sqlite3.connect(temp_db)
    try:
        fact_id = conn.execute("SELECT rowid FROM facts WHERE fact_text = ?", (fact_text,)).fetchone()[0]
    finally:
        conn.close()
    SemanticEmbeddingStore(db_path=temp_db).upsert_embedding(
        EmbeddingInput(owner_type=SEMANTIC_FACT_OWNER_TYPE, owner_id=str(fact_id), text=fact_text)
    )

    semantic = retrieve_semantic_facts(
        RetrievalRequest(query="what timezone is Priya in?", per_source_limit=3, task_type="broad_memory"),
        db_path=temp_db,
    )

    assert semantic.candidates == tuple()
