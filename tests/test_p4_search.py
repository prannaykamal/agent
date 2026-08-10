import pytest
from fastapi.testclient import TestClient
from src.db import init_db
from src.mcp_gateway.search import perform_web_search, search_web
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


def test_search_mcp_wrapper_returns_no_local_fallback_when_unavailable(temp_db, monkeypatch):
    from src.tools.mcp_invocation import MCPInvocationResult, MCPInvocationStatus

    monkeypatch.setattr(
        "src.tools.mcp_invocation.invoke_provider_tool",
        lambda *args, **kwargs: MCPInvocationResult(status=MCPInvocationStatus.PROVIDER_UNAVAILABLE),
    )

    assert perform_web_search("LangGraph state machine", max_results=2) == []
    assert "Unavailable" in search_web.invoke({"query": "FastAPI async endpoints"})


def test_search_rest_api_endpoint_shape_when_unavailable(temp_db):
    resp = client.get("/api/search?q=Python&max_results=3")
    assert resp.status_code == 200
    data = resp.json()
    assert data["query"] == "Python"
    assert data["results"] == []
    assert data["total_results"] == 0
