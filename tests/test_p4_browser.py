import os
import pytest
from fastapi.testclient import TestClient
from src.db import init_db
from src.mcp_gateway.sandboxes.browser_sandbox import safe_browse_url, capture_screenshot
from src.api.server import app

@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_p4_browser.db"
    mem_file = tmp_path / "MEMORY.md"

    monkeypatch.setattr("src.db.DB_PATH", db_file)
    monkeypatch.setattr("src.config.MEMORY_PATH", mem_file)
    init_db(db_file)
    return db_file

client = TestClient(app)

def test_browser_sandbox_source_tools_remain_until_t3(temp_db):
    """T2 keeps browser sandbox source symbols on disk for later T3 deletion."""
    assert safe_browse_url.name == "safe_browse_url"
    assert capture_screenshot.name == "capture_screenshot"

def test_browser_rest_api_endpoints(temp_db, tmp_path):
    """Verifies REST API endpoints POST /api/browser/browse and POST /api/browser/screenshot."""
    resp_browse = client.post("/api/browser/browse", json={"url": "https://example.com"})
    assert resp_browse.status_code == 200
    assert resp_browse.json()["status"] == "blocked"
    assert "removed or blocked" in resp_browse.json()["result"]

    out_png = str(tmp_path / "api_shot.png")
    resp_shot = client.post("/api/browser/screenshot", json={"url": "https://example.com", "save_path": out_png})
    assert resp_shot.status_code == 200
    assert resp_shot.json()["status"] == "blocked"
    assert "removed or blocked" in resp_shot.json()["result"]
    assert not os.path.exists(out_png)
