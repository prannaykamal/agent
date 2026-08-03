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

def test_safe_browse_url_title_and_metadata(temp_db):
    """Verifies safe_browse_url extracts title, URL, and clean markdown text."""
    res_text = safe_browse_url.invoke({"url": "https://example.com"})
    assert "Title:" in res_text
    assert "URL: https://example.com" in res_text
    assert "[Browser Sandbox" in res_text

def test_capture_screenshot_tool(temp_db, tmp_path):
    """Verifies capture_screenshot creates PNG screenshot image file on disk."""
    out_png = str(tmp_path / "shot_test.png")
    res = capture_screenshot.invoke({"url": "https://example.com", "save_path": out_png})
    assert "Saved screenshot" in res
    assert os.path.exists(out_png)
    assert os.path.getsize(out_png) > 0

def test_browser_rest_api_endpoints(temp_db, tmp_path):
    """Verifies REST API endpoints POST /api/browser/browse and POST /api/browser/screenshot."""
    resp_browse = client.post("/api/browser/browse", json={"url": "https://example.com"})
    assert resp_browse.status_code == 200
    assert "Title:" in resp_browse.json()["result"]

    out_png = str(tmp_path / "api_shot.png")
    resp_shot = client.post("/api/browser/screenshot", json={"url": "https://example.com", "save_path": out_png})
    assert resp_shot.status_code == 200
    assert "Saved screenshot" in resp_shot.json()["result"]
