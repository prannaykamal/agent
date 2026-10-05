import pytest
from fastapi.testclient import TestClient

from src.api.server import app
from src.db import init_db
from src.memory.schema import MEMORY_TABLES


client = TestClient(app)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "phase2_api.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file


def test_data_inspector_lists_phase2_tables(temp_db):
    response = client.get("/api/data/tables")

    assert response.status_code == 200
    tables = set(response.json()["tables"])
    assert set(MEMORY_TABLES).issubset(tables)


def test_data_inspector_reads_phase2_tables(temp_db):
    for table_name in MEMORY_TABLES:
        response = client.get(f"/api/data/table/{table_name}")

        assert response.status_code == 200
        data = response.json()
        assert data["table"] == table_name
        assert data["rows"] == []
        assert data["columns"] == []
        assert data["total_rows"] == 0


def test_data_inspector_rejects_unallowed_table(temp_db):
    response = client.get("/api/data/table/sqlite_master")

    assert response.status_code == 400
    assert "not allowed" in response.json()["detail"]
