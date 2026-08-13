import pytest
import sqlite3
from pathlib import Path
from langchain_core.messages import HumanMessage, AIMessage

from src.db import init_db
from src.memory.episodic import log_episode, search_episodes_fts
from src.memory.semantic import add_semantic_fact, search_facts_top_k, sync_memory_md, extract_and_save_facts
from src.memory.procedural import add_procedural_skill, sync_skills_from_md, match_procedural_skills
from src.memory.retrieval_gate import should_retrieve_memory
from src.harness.graph import agent_app

@pytest.fixture
def temp_env(tmp_path):
    db_file = tmp_path / "test_state.db"
    mem_file = tmp_path / "MEMORY.md"
    skill_file = tmp_path / "SKILL.md"

    init_db(db_file)
    return {
        "db": db_file,
        "mem": mem_file,
        "skill": skill_file
    }

def test_episodic_memory_fts(temp_env):
    db_path = temp_env["db"]
    log_episode("sess_01", "User asked about project deadlines", outcome="success", db_path=db_path)
    log_episode("sess_02", "User asked about lunch recipes", outcome="success", db_path=db_path)

    results = search_episodes_fts("deadlines", db_path=db_path)
    assert len(results) >= 1
    assert "project deadlines" in results[0]["content"]

def test_semantic_memory_top_k_and_sync(temp_env):
    db_path = temp_env["db"]
    mem_path = temp_env["mem"]

    add_semantic_fact(category="user_preference", fact_text="User prefers Python over Java", db_path=db_path, memory_path=mem_path)
    add_semantic_fact(category="user_profile", fact_text="User works as a Software Architect", db_path=db_path, memory_path=mem_path)

    top_k = search_facts_top_k("Python", k=2, db_path=db_path)
    assert len(top_k) >= 1
    assert "Python" in top_k[0]["fact_text"]

    # Verify MEMORY.md synced file
    mem_content = mem_path.read_text(encoding="utf-8")
    assert "User prefers Python over Java" in mem_content
    assert "User works as a Software Architect" in mem_content

def test_procedural_memory_sync_and_match(temp_env):
    db_path = temp_env["db"]
    skill_path = temp_env["skill"]

    skill_path.write_text(
        "# Skills Catalog\n\n### 1. Code Review Workflow\n- **Trigger**: review, pull request, code inspection\n- **Action**: Inspect code style and security vulnerabilities.",
        encoding="utf-8"
    )

    sync_skills_from_md(skill_path=skill_path, db_path=db_path)
    matches = match_procedural_skills("Can you review this code pull request?", db_path=db_path)

    assert len(matches) >= 1
    assert matches[0]["name"] == "Code Review Workflow"

def test_retrieval_gate():
    # Math & greetings should skip retrieval
    assert should_retrieve_memory("2 + 2") is False
    assert should_retrieve_memory("hello") is False

    # Personal memory queries should trigger retrieval
    assert should_retrieve_memory("What did I say about my meeting?") is True
    assert should_retrieve_memory("Remember that I prefer morning slots") is True
    assert should_retrieve_memory("Who am I meeting tomorrow?") is True

def test_end_to_end_memory_workflow(temp_env, monkeypatch):
    db_path = temp_env["db"]
    mem_path = temp_env["mem"]

    # Monkeypatch helpers to use temp_env
    monkeypatch.setattr("src.db.DB_PATH", db_path)
    monkeypatch.setattr("src.config.DB_PATH", db_path)
    monkeypatch.setattr("src.config.MEMORY_PATH", mem_path)
    monkeypatch.setattr("src.harness.graph.search_facts_top_k", lambda query, k: search_facts_top_k(query, k, db_path=db_path))
    monkeypatch.setattr("src.harness.graph.search_episodes_fts", lambda query, limit: search_episodes_fts(query, limit, db_path=db_path))
    monkeypatch.setattr("src.harness.graph.match_procedural_skills", lambda query: match_procedural_skills(query, db_path=db_path))
    monkeypatch.setattr("src.harness.graph.log_episode", lambda session_id, content: log_episode(session_id, content, db_path=db_path))
    monkeypatch.setattr("src.harness.graph.extract_and_save_facts", lambda user_input, assistant_output: extract_and_save_facts(user_input, assistant_output, db_path=db_path, memory_path=mem_path))

    # Add a initial fact
    add_semantic_fact(category="user_preference", fact_text="User prefers dark theme mode", db_path=db_path, memory_path=mem_path)

    # Invoke graph turn
    input_state = {
        "messages": [HumanMessage(content="Remember that my name is Alex and I prefer dark theme mode")],
        "session_id": "test_session_mem",
        "summary": "",
        "token_count": 0,
        "retrieval_triggered": False,
        "retrieved_memories": []
    }

    result = agent_app.invoke(input_state)

    assert result["retrieval_triggered"] is True
    assert len(result["messages"]) >= 2
    
    # Check MEMORY.md was updated during consolidation
    mem_content = mem_path.read_text(encoding="utf-8")
    assert "Alex" in mem_content or "dark theme mode" in mem_content
