import pytest
from fastapi.testclient import TestClient

from src.api.server import app
from src.db import init_db
from src.memory.semantic import add_semantic_fact


@pytest.fixture
def temp_paths(tmp_path, monkeypatch):
    db_file = tmp_path / "phase7b_inspector.db"
    mem_file = tmp_path / "MEMORY.md"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    monkeypatch.setattr("src.config.MEMORY_PATH", mem_file)
    monkeypatch.setattr("src.api.server.MEMORY_PATH", mem_file)
    init_db(db_file)
    return db_file, mem_file


@pytest.fixture
def client():
    return TestClient(app)


def test_data_inspector_reads_semantic_embeddings_and_dedup_events(client, temp_paths):
    db_path, mem_path = temp_paths
    add_semantic_fact("user_pref", "User prefers FastAPI", db_path=db_path, memory_path=mem_path)

    embeddings = client.get("/api/data/table/semantic_embeddings")
    events = client.get("/api/data/table/semantic_dedup_events")

    assert embeddings.status_code == 200
    assert embeddings.json()["table"] == "semantic_embeddings"
    assert embeddings.json()["rows"]
    assert events.status_code == 200
    assert events.json()["table"] == "semantic_dedup_events"
    assert events.json()["rows"][0]["action"] == "NEW"
