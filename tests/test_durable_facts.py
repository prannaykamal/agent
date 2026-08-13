from src.memory.durable_facts import (
    is_ephemeral_fact,
    should_promote_durable_fact,
    promote_durable_candidates,
)
from src.memory.semantic_candidates import PendingFactCandidateRecord
from src.db import init_db
from src.memory.semantic_store import SemanticFactStore


def test_durable_gate_requires_flag_confidence_and_non_ephemeral_text():
    assert should_promote_durable_fact(
        fact_text="Prannay's email is prannay@kamal.dev",
        category="user_fact",
        confidence=0.92,
        durable=True,
    )
    assert should_promote_durable_fact(
        fact_text="User prefers compact answers",
        category="preference",
        confidence=0.81,
        durable=False,
    ) is False
    assert should_promote_durable_fact(
        fact_text="User asked to send five emails",
        category="user_fact",
        confidence=0.99,
        durable=True,
    ) is False
    assert is_ephemeral_fact("Send mail to Prannay saying hi") is True


def test_promote_durable_candidates_writes_permanent_facts(tmp_path, monkeypatch):
    db_file = tmp_path / "durable.db"
    mem_file = tmp_path / "MEMORY.md"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    monkeypatch.setattr("src.config.MEMORY_PATH", mem_file)
    init_db(db_file)

    durable = PendingFactCandidateRecord(
        id="fact_candidate_durable",
        session_id="sess",
        source_message_id="u1",
        source_episode_id=None,
        fact="You can reach Prannay at prannay@kamal.dev",
        category="user_fact",
        confidence=0.91,
        explicit=False,
        source="secondary_llm_candidate",
        status="PENDING",
        batch_id="job-1",
        metadata={"durable": True},
        created_at="now",
        updated_at="now",
        processed_at=None,
    )
    skipped = PendingFactCandidateRecord(
        id="fact_candidate_skip",
        session_id="sess",
        source_message_id="u1",
        source_episode_id=None,
        fact="User prefers compact answers",
        category="user_preference",
        confidence=0.81,
        explicit=False,
        source="secondary_llm_candidate",
        status="PENDING",
        batch_id="job-1",
        metadata={"durable": False},
        created_at="now",
        updated_at="now",
        processed_at=None,
    )

    promoted = promote_durable_candidates([durable, skipped], db_path=db_file, memory_path=mem_file)
    facts = SemanticFactStore(db_path=db_file).list_facts()

    assert promoted == 1
    assert any("prannay@kamal.dev" in fact.fact_text for fact in facts)
    assert all("compact answers" not in fact.fact_text for fact in facts)
    assert "prannay@kamal.dev" in mem_file.read_text(encoding="utf-8")
