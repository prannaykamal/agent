import json
import pytest
from fastapi.testclient import TestClient

from src.api.server import app
from src.mcp_gateway.sandboxes.code_sandbox import github_clone, github_commit_and_push, github_merge
from src.mcp_gateway.calendar import calendar_inspect_availability, calendar_create_event
from src.mcp_gateway.communication import whatsapp_read, whatsapp_send, telegram_read, telegram_send

client = TestClient(app)

def test_github_tools_return_structured_failures(tmp_path):
    """P1 Item 1, 2, 3: Verifies GitHub tools return structured failure JSON with exit_code, stdout, stderr when commands fail."""
    target_dir = tmp_path / "invalid_clone_target"

    # Test clone with invalid repository URL
    res_clone_str = github_clone.invoke({"repo_url": "https://invalid.github.com/nonexistent_repo_12345.git", "target_dir": str(target_dir)})
    res_clone = json.loads(res_clone_str)
    assert res_clone["status"] == "FAILED"
    assert res_clone["exit_code"] != 0
    assert "stderr" in res_clone
    assert "stdout" in res_clone
    assert "GitHub Error" in res_clone["message"]


    # Test merge with invalid repo directory
    res_merge_str = github_merge.invoke({"source_branch": "feature", "target_branch": "main", "repo_dir": "/nonexistent_dir_999"})
    res_merge = json.loads(res_merge_str)
    assert res_merge["status"] == "FAILED"
    assert res_merge["exit_code"] != 0
    assert "stderr" in res_merge

def test_calendar_local_storage_banner():
    """P1 Item 4, 5: Verifies calendar tools display local-only storage banners when credentials are missing."""
    res_inspect = calendar_inspect_availability.invoke({"start_date": "2026-08-01", "end_date": "2026-08-02"})
    assert "[Calendar MCP (Local SQLite Storage)]" in res_inspect

    res_create = calendar_create_event.invoke({"title": "Sync Test", "start_time": "2026-08-01 10:00", "end_time": "2026-08-01 11:00"})
    assert "[Calendar MCP (Local SQLite Storage)]" in res_create

def test_whatsapp_telegram_local_storage_banners():
    """P1 Item 6, 7: Verifies WhatsApp and Telegram tools state local SQLite storage banners."""
    res_wa_read = whatsapp_read.invoke({"limit": 5})
    assert "[WhatsApp MCP (Local SQLite Storage)]" in res_wa_read

    res_wa_send = whatsapp_send.invoke({"recipient": "+1234567890", "message": "Test WA"})
    assert "[WhatsApp MCP (Local SQLite Storage) - SENT]" in res_wa_send

    res_tg_read = telegram_read.invoke({"limit": 5})
    assert "[Telegram MCP (Local SQLite Storage)]" in res_tg_read

    res_tg_send = telegram_send.invoke({"chat_id": "12345", "text": "Test TG"})
    assert "[Telegram MCP (Local SQLite Storage) - SENT]" in res_tg_send

def test_api_integrations_status():
    """P1 Item 8: Verifies GET /api/integrations/status endpoint returns provider capabilities and truthfulness tags."""
    response = client.get("/api/integrations/status")
    assert response.status_code == 200
    data = response.json()
    assert "integrations" in data
    integrations = data["integrations"]

    assert "github" in integrations
    assert integrations["github"]["truthfulness"] == "REAL_SUBPROCESS"

    assert "calendar" in integrations
    assert integrations["calendar"]["truthfulness"] in ("LOCAL_ONLY_STORAGE", "REAL_API")

    assert "whatsapp" in integrations
    assert integrations["whatsapp"]["truthfulness"] == "LOCAL_ONLY_STORAGE"

    assert "telegram" in integrations
    assert integrations["telegram"]["truthfulness"] == "LOCAL_ONLY_STORAGE"

    assert "search" in integrations
    assert integrations["search"]["truthfulness"] == "REAL_LIVE_FETCH"

    assert "browser" in integrations
    assert integrations["browser"]["truthfulness"] == "REAL_HTTP_FETCH"
