import pytest
from fastapi.testclient import TestClient
from src.db import init_db
from src.mcp_gateway.search import search_web
from src.mcp_gateway.search_adapters import perform_web_search
from src.api.server import app

@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_p4_search.db"
    mem_file = tmp_path / "MEMORY.md"

    monkeypatch.setattr("src.db.DB_PATH", db_file)
    monkeypatch.setattr("src.config.MEMORY_PATH", mem_file)
    init_db(db_file)
    return db_file

client = TestClient(app)

def test_search_adapters_structured_output(temp_db):
    """Verifies perform_web_search returns structured list of dicts with title, url, snippet."""
    results = perform_web_search("LangGraph state machine", max_results=2)
    assert isinstance(results, list)
    assert len(results) >= 1
    for item in results:
        assert "title" in item
        assert "url" in item
        assert "snippet" in item

def test_search_web_tool_citations(temp_db):
    """Verifies search_web tool formats structured text with citations."""
    res_text = search_web.invoke({"query": "FastAPI async endpoints"})
    assert "[Live Web Search Results" in res_text
    assert "Source:" in res_text

def test_search_rest_api_endpoint(temp_db):
    """Verifies GET /api/search?q=Python returns structured payload."""
    resp = client.get("/api/search?q=Python&max_results=3")
    assert resp.status_code == 200
    data = resp.json()
    assert data["query"] == "Python"
    assert "results" in data
    assert len(data["results"]) >= 1
    assert "title" in data["results"][0]
