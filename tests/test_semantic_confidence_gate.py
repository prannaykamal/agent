import pytest
from src.db import init_db
from src.memory.semantic import (
    process_fact_candidates,
    get_pending_facts,
    get_all_semantic_facts,
    should_run_periodic_consolidation,
    run_periodic_consolidation
)
from src.memory.episodic import log_episode

@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_gate.db"
    mem_file = tmp_path / "MEMORY.md"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    monkeypatch.setattr("src.config.MEMORY_PATH", mem_file)
    init_db(db_file)
    return db_file, mem_file

def test_phase7a_candidate_queue_routing(temp_db):
    db_file, mem_file = temp_db

    candidates = [
        {"fact": "User explicitly requires Python 3.11", "confidence": 0.95, "category": "tech_stack", "source": "explicit_user", "explicit": True},
        {"fact": "User might prefer dark mode UI", "confidence": 0.85, "category": "user_preference", "source": "inferred", "explicit": False}
    ]

    process_fact_candidates("sess_gate", candidates, db_path=db_file, memory_path=mem_file)

    facts = get_all_semantic_facts(db_path=db_file)
    assert facts == []

    pending = get_pending_facts(db_path=db_file)
    assert len(pending) == 2
    assert any("Python 3.11" in p["fact_text"] for p in pending)
    assert any("dark mode" in p["fact_text"] and p["confidence"] == 0.85 for p in pending)

def test_periodic_consolidation_trigger(temp_db, monkeypatch):
    db_file, mem_file = temp_db
    monkeypatch.setenv("OPENAI_API_KEY", "your_openai_api_key_here")

    # Add 10 episodes to hit 10-episode milestone
    for i in range(10):
        log_episode("sess_consolidation", f"Turn content {i}", db_path=db_file)

    assert should_run_periodic_consolidation(db_path=db_file) is True

    # Process a pending fact
    candidates = [{"fact": "User prefers FastAPI framework", "confidence": 0.82, "category": "framework", "source": "inferred", "explicit": False}]
    process_fact_candidates("sess_consolidation", candidates, db_path=db_file, memory_path=mem_file)

    res = run_periodic_consolidation(provider="openai", db_path=db_file, memory_path=mem_file)
    assert res["status"] == "success"

    # Pending queue should now be cleared
    assert len(get_pending_facts(db_path=db_file)) == 0

