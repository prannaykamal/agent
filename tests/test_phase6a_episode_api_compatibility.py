import pytest
from fastapi.testclient import TestClient

from src.api.server import app
from src.db import init_db
from src.memory.episode_store import StructuredEpisodeRepository, StructuredEpisodeWrite
from src.memory.episodic import log_episode


client = TestClient(app)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "phase6a_api.db"
    mem_file = tmp_path / "MEMORY.md"
    skill_file = tmp_path / "SKILL.md"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    monkeypatch.setattr("src.config.MEMORY_PATH", mem_file)
    monkeypatch.setattr("src.config.SKILL_PATH", skill_file)
    init_db(db_file)
    return db_file


def _episode():
    return StructuredEpisodeWrite(
        id="api-structured-episode",
        session_id="api-session",
        title="API-visible structured episode",
        summary="The data inspector can read structured episode rows.",
        participants=["User", "Assistant"],
        goals=["Verify data inspector"],
        decisions=["Do not alter full memory endpoint"],
        artifacts=[],
        topics=["API", "Episodic memory"],
        importance=0.8,
        start_message_id="turn-api-1",
        end_message_id="turn-api-2",
        source="phase6a.api.test",
        source_job_id="job-api-episode",
    )


def test_data_inspector_reads_inserted_structured_episode(temp_db):
    repository = StructuredEpisodeRepository(db_path=temp_db)
    repository.append_episode(_episode())

    tables_response = client.get("/api/data/tables")
    assert tables_response.status_code == 200
    assert "structured_episodes" in tables_response.json()["tables"]

    table_response = client.get("/api/data/table/structured_episodes")
    assert table_response.status_code == 200
    data = table_response.json()
    assert data["table"] == "structured_episodes"
    assert data["total_rows"] == 1
    assert data["rows"][0]["id"] == "api-structured-episode"
    assert data["rows"][0]["title"] == "API-visible structured episode"
    assert "participants_json" in data["columns"]


def test_api_memory_full_response_shape_unchanged_and_legacy_episode_only(temp_db):
    StructuredEpisodeRepository(db_path=temp_db).append_episode(_episode())
    log_episode("api-session", "Legacy episode mentions API compatibility", outcome="success", db_path=temp_db)

    response = client.get("/api/memory/full?query=API")

    assert response.status_code == 200
    data = response.json()
    assert set(data.keys()) == {"facts", "episodes", "soul_md", "skill_md", "memory_md"}
    assert isinstance(data["episodes"], list)
    assert len(data["episodes"]) == 1
    assert data["episodes"][0]["session_id"] == "api-session"
    assert "Legacy episode" in data["episodes"][0]["content"]
    assert "API-visible structured episode" not in data["episodes"][0]["content"]

