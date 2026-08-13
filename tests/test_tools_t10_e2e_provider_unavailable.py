import json

import pytest
from fastapi.testclient import TestClient

from src.api.server import app
from src.db import init_db
from src.harness.graph import get_registered_tools
from src.tools.mcp_invocation import MCPInvocationStatus, invoke_provider_tool
from src.tools.mcp_provider_registry import clear_mcp_provider_discovery_cache


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_file = tmp_path / "tools_t10_provider_unavailable.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    monkeypatch.setattr("src.tools.mcp_provider_config.AGENT_DIR", tmp_path / ".agent")
    clear_mcp_provider_discovery_cache()
    init_db(db_file)
    return TestClient(app)


def test_t10_app_api_survives_without_target_mcp_providers(client):
    providers = client.get("/api/tools/mcp/providers")
    assert providers.status_code == 200
    body = providers.json()
    provider_ids = {item["provider_id"] for item in body["providers"]}
    assert provider_ids >= {"search_tavily", "search_duckduckgo", "google_calendar", "gmail"}
    assert "whatsapp" not in provider_ids
    assert "telegram" not in provider_ids
    assert all(item["availability_status"] == "unavailable" for item in body["providers"])

    tools_status = client.get("/api/tools/status")
    assert tools_status.status_code == 200
    assert tools_status.json()["providers"]["available_providers"] == 0

    overview = client.get("/api/tools/observability/overview")
    assert overview.status_code == 200
    assert "providers" in overview.json()


def test_t10_unavailable_provider_tools_are_not_bindable(client):
    tools, tool_map = get_registered_tools()
    names = {tool.name for tool in tools}

    assert "heartbeat" in names
    for provider_tool in {"search_web", "calendar_create_event", "email_send", "whatsapp_send", "telegram_send"}:
        assert provider_tool not in names
        assert provider_tool not in tool_map


def test_t10_mcp_invocation_returns_safe_unavailable_without_fallback(tmp_path):
    clear_mcp_provider_discovery_cache()
    result = invoke_provider_tool(
        provider_ids=("gmail",),
        tool_hints=("send",),
        arguments={"to": "user@example.com", "body": "hello"},
        config_path=tmp_path / "missing_mcp_config.json",
    )

    assert result.status == MCPInvocationStatus.PROVIDER_UNAVAILABLE
    text = result.to_text("Gmail MCP")
    assert "unavailable" in text.lower()
    assert "smtp" not in json.dumps(result.__dict__).lower()
