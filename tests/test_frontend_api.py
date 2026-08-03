import pytest
from fastapi.testclient import TestClient
from src.db import init_db
from src.api.server import app

@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_frontend_api.db"
    mem_file = tmp_path / "MEMORY.md"

    monkeypatch.setattr("src.db.DB_PATH", db_file)
    monkeypatch.setattr("src.config.MEMORY_PATH", mem_file)
    init_db(db_file)
    return db_file

client = TestClient(app)

def test_get_data_tables(temp_db):
    resp = client.get("/api/data/tables")
    assert resp.status_code == 200
    data = resp.json()
    assert "tables" in data
    assert "facts" in data["tables"]
    assert "episodes" in data["tables"]
    assert "loop_events" in data["tables"]

def test_get_data_table_rows(temp_db):
    resp = client.get("/api/data/table/facts")
    assert resp.status_code == 200
    data = resp.json()
    assert data["table"] == "facts"
    assert "rows" in data
    assert "columns" in data

def test_get_data_table_invalid(temp_db):
    resp = client.get("/api/data/table/non_existent_table")
    assert resp.status_code == 400
    assert "not allowed" in resp.json()["detail"]
