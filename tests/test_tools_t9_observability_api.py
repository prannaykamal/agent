import json

import pytest
from fastapi.testclient import TestClient

from src.api.server import app
from src.db import get_connection, init_db
from src.hitl.audit_logger import log_audit_event


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_file = tmp_path / "tools_t9_api.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    monkeypatch.setattr("src.mcp_gateway.registry.load_live_mcp_tools", lambda: [])
    init_db(db_file)
    return TestClient(app)


def _table_count(table_name):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(f"SELECT COUNT(*) AS count FROM {table_name}")
    count = cursor.fetchone()["count"]
    conn.close()
    return count


def test_t9_tools_status_and_overview_work_and_show_final_groups(client):
    status = client.get("/api/tools/status")
    assert status.status_code == 200
    body = status.json()
    assert body["status"] == "OK"
    assert body["registry"]["group_counts"]["personal_os"] >= 1
    assert body["registry"]["group_counts"]["removed"] >= 1
    assert body["removed_tools"]["active"] == 0

    overview = client.get("/api/tools/observability/overview")
    assert overview.status_code == 200
    data = overview.json()
    assert "registry" in data
    assert "providers" in data
    assert "policy" in data
    assert "tool_calls" in data
    assert "blocked" in data


def test_t9_calls_results_audit_and_blocked_endpoints_are_read_only(client):
    log_audit_event("sess", "run_code", "Blocked", "REMOVED_TOOL_BLOCKED", {"api_key": "secret"}, "blocked sandbox")
    before = {name: _table_count(name) for name in ["tool_calls", "tool_results", "audit_logs", "approval_requests", "tool_schedules", "tool_schedule_runs"]}

    for path in [
        "/api/tools/observability/calls",
        "/api/tools/observability/results",
        "/api/tools/observability/audit",
        "/api/tools/observability/blocked",
        "/api/tools/status",
        "/api/tools/observability/overview",
    ]:
        response = client.get(path)
        assert response.status_code == 200

    after = {name: _table_count(name) for name in before}
    assert after == before
    blocked = client.get("/api/tools/observability/blocked").json()
    assert blocked["blocked_attempts"]
    assert "secret" not in json.dumps(blocked).lower()


def test_t9_provider_status_is_frontend_safe(client):
    response = client.get("/api/tools/mcp/providers")
    external_response = client.get("/api/tools/external/providers")
    assert response.status_code == 200
    assert external_response.status_code == 200
    providers = response.json()["providers"]
    external = external_response.json()["providers"]
    mcp_ids = {provider["provider_id"] for provider in providers}
    external_ids = {provider["provider_id"] for provider in external}
    assert mcp_ids >= {"gmail", "google_calendar", "search_tavily", "search_duckduckgo"}
    assert "whatsapp" not in mcp_ids
    assert "telegram" not in mcp_ids
    assert external_ids >= {"whatsapp_api", "telegram_bot_api"}
    for provider in providers + external:
        assert "provider_id" in provider
        assert "availability_status" in provider
        assert "env" not in provider
