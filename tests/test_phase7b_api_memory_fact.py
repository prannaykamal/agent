import sqlite3

import pytest
from fastapi.testclient import TestClient

from src.api.server import app
from src.db import init_db


@pytest.fixture
def temp_paths(tmp_path, monkeypatch):
    db_file = tmp_path / "phase7b_api.db"
    mem_file = tmp_path / "MEMORY.md"
    soul_file = tmp_path / "SOUL.md"
    skill_file = tmp_path / "SKILL.md"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    monkeypatch.setattr("src.config.MEMORY_PATH", mem_file)
    monkeypatch.setattr("src.api.server.MEMORY_PATH", mem_file)
    monkeypatch.setattr("src.api.server.SOUL_PATH", soul_file)
    monkeypatch.setattr("src.api.server.SKILL_PATH", skill_file)
    init_db(db_file)
    return db_file, mem_file


@pytest.fixture
def client():
    return TestClient(app)


def _count(db_path, table):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def test_api_memory_fact_shape_unchanged_for_new(client, temp_paths):
    db_path, mem_path = temp_paths

    response = client.post("/api/memory/fact", json={"category": "user_pref", "fact_text": "Prefers FastAPI"})

    assert response.status_code == 200
    assert response.json() == {"status": "success", "message": "Fact saved and MEMORY.md synced."}
    assert _count(db_path, "facts") == 1
    assert _count(db_path, "semantic_embeddings") == 1
    assert _count(db_path, "semantic_dedup_events") == 1
    assert "Prefers FastAPI" in mem_path.read_text(encoding="utf-8")


def test_api_memory_fact_shape_unchanged_for_duplicate(client, temp_paths):
    db_path, _ = temp_paths

    first = client.post("/api/memory/fact", json={"category": "user_pref", "fact_text": "Prefers FastAPI"})
    second = client.post("/api/memory/fact", json={"category": "user_pref", "fact_text": "Prefers FastAPI"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == {"status": "success", "message": "Fact saved and MEMORY.md synced."}
    assert _count(db_path, "facts") == 1
    assert _count(db_path, "semantic_dedup_events") == 2


def test_api_memory_and_full_shapes_unchanged(client, temp_paths):
    client.post("/api/memory/fact", json={"category": "user_pref", "fact_text": "Prefers FastAPI"})

    memory = client.get("/api/memory")
    full = client.get("/api/memory/full")

    assert memory.status_code == 200
    assert set(memory.json()) == {"facts", "total_facts"}
    assert full.status_code == 200
    assert set(full.json()) == {"facts", "episodes", "soul_md", "skill_md", "memory_md"}
