import pytest
from src.db import init_db
from src.memory.episodic import (
    should_trigger_episode,
    generate_structured_episode_summary,
    create_structured_episode,
    search_episodes_fts
)

@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_episodic.db"
    mem_file = tmp_path / "MEMORY.md"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    monkeypatch.setattr("src.config.MEMORY_PATH", mem_file)
    init_db(db_file)
    return db_file

def test_episode_detector_rules():
    assert should_trigger_episode("sess_1", task_completed=True) is True
    assert should_trigger_episode("sess_1", workflow_finished=True) is True
    assert should_trigger_episode("sess_1", trimming_occurred=True) is True
    assert should_trigger_episode("sess_1", conversation_idle_seconds=2800) is True
    assert should_trigger_episode("sess_1", conversation_tokens=55000) is True
    assert should_trigger_episode("sess_1") is False

def test_structured_summary_generator(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "your_openai_api_key_here")
    summary = generate_structured_episode_summary("sess_test", "User designed HITL system", provider="openai")

    assert "title" in summary
    assert "summary" in summary
    assert "participants" in summary
    assert "goals" in summary
    assert "decisions" in summary

def test_create_structured_episode(temp_db):
    data = {
        "title": "Designed HITL architecture",
        "summary": "Implemented deterministic risk classifier and approval engine.",
        "participants": ["User", "Assistant"],
        "goals": ["Implement approval system"],
        "decisions": ["Use Policy Engine"],
        "artifacts": ["policy.yaml"],
        "topics": ["LangGraph", "HITL"],
        "importance": 0.92
    }

    create_structured_episode("sess_hitl", data, db_path=temp_db)

    episodes = search_episodes_fts("HITL", db_path=temp_db)
    assert len(episodes) >= 1
    assert episodes[0]["session_id"] == "sess_hitl"
    assert "Designed HITL architecture" in episodes[0]["content"]
