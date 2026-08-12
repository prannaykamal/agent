from fastapi.testclient import TestClient

from src.api.server import app
from src.tools.mcp_provider_registry import clear_mcp_provider_discovery_cache


client = TestClient(app)


def test_t6_mcp_provider_status_api_lists_all_target_providers():
    clear_mcp_provider_discovery_cache()

    response = client.get("/api/tools/mcp/providers")

    assert response.status_code == 200
    data = response.json()
    provider_ids = {provider["provider_id"] for provider in data["providers"]}
    assert provider_ids == {
        "search_tavily",
        "search_duckduckgo",
        "google_calendar",
        "gmail",
    }
    assert "whatsapp" not in provider_ids
    assert "telegram" not in provider_ids
    assert all("tools" in provider for provider in data["providers"])


def test_t6_mcp_provider_detail_api_returns_unavailable_missing_provider(monkeypatch):
    monkeypatch.setattr("src.tools.mcp_provider_config.load_mcp_config_data", lambda config_path=None: {})
    clear_mcp_provider_discovery_cache()

    response = client.get("/api/tools/mcp/providers/gmail")

    assert response.status_code == 200
    data = response.json()
    assert data["provider_id"] == "gmail"
    assert data["availability_status"] == "unavailable"
    assert data["configured"] is False


def test_t6_mcp_provider_detail_api_404s_for_unknown_provider():
    response = client.get("/api/tools/mcp/providers/not_a_provider")

    assert response.status_code == 404


def test_t6_mcp_provider_api_can_return_mocked_discovered_tools(monkeypatch):
    fake_statuses = [
        {
            "provider_id": "gmail",
            "display_name": "Gmail MCP",
            "enabled": True,
            "transport_type": "stdio",
            "credential_status": "configured",
            "discovery_status": "discovered",
            "availability_status": "available",
            "configured": True,
            "expected_tool_hints": ["mail"],
            "last_discovered_at": "2026-08-11T00:00:00+00:00",
            "last_error": None,
            "tool_count": 1,
            "tools": [{"tool_id": "mcp.gmail.gmail_send", "provider_managed": True}],
        }
    ]

    monkeypatch.setattr("src.tools.mcp_provider_registry.get_mcp_provider_statuses", lambda include_config=False: fake_statuses)
    monkeypatch.setattr(
        "src.tools.mcp_provider_registry.get_mcp_provider_status",
        lambda provider_id, include_config=False: fake_statuses[0] if provider_id == "gmail" else None,
    )

    list_response = client.get("/api/tools/mcp/providers")
    detail_response = client.get("/api/tools/mcp/providers/gmail")

    assert list_response.status_code == 200
    assert list_response.json()["providers"][0]["availability_status"] == "available"
    assert detail_response.status_code == 200
    assert detail_response.json()["tools"][0]["tool_id"] == "mcp.gmail.gmail_send"


def test_t6_api_tools_shape_remains_compatible():
    response = client.get("/api/tools")

    assert response.status_code == 200
    data = response.json()
    assert set(data) == {"total_tools", "personal_os_tools", "mcp_tools"}
    assert isinstance(data["personal_os_tools"], list)
    assert isinstance(data["mcp_tools"], list)


def test_t6_mcp_provider_discover_endpoint_is_explicit_metadata_refresh(monkeypatch):
    fake_status = {
        "provider_id": "gmail",
        "display_name": "Gmail MCP",
        "enabled": True,
        "transport_type": "stdio",
        "credential_status": "configured",
        "discovery_status": "discovered",
        "availability_status": "available",
        "configured": True,
        "expected_tool_hints": ["mail"],
        "last_discovered_at": "2026-08-11T00:00:00+00:00",
        "last_error": None,
        "tool_count": 1,
        "tools": [{"tool_id": "mcp.gmail.gmail_search", "provider_managed": True}],
    }
    calls = []

    def fake_get_status(provider_id, refresh=False, include_config=False):
        calls.append({"provider_id": provider_id, "refresh": refresh, "include_config": include_config})
        return fake_status if provider_id == "gmail" else None

    monkeypatch.setattr("src.tools.mcp_provider_registry.get_mcp_provider_status", fake_get_status)

    response = client.post("/api/tools/mcp/providers/gmail/discover")

    assert response.status_code == 200
    assert response.json()["availability_status"] == "available"
    assert calls == [{"provider_id": "gmail", "refresh": True, "include_config": False}]


def test_t6_whatsapp_telegram_are_direct_external_api_providers_not_mcp():
    mcp_response = client.get("/api/tools/mcp/providers")
    external_response = client.get("/api/tools/external/providers")

    assert mcp_response.status_code == 200
    assert external_response.status_code == 200
    mcp_ids = {provider["provider_id"] for provider in mcp_response.json()["providers"]}
    external_ids = {provider["provider_id"] for provider in external_response.json()["providers"]}

    assert "whatsapp" not in mcp_ids
    assert "telegram" not in mcp_ids
    assert {"whatsapp_api", "telegram_bot_api"}.issubset(external_ids)


def test_t6_unknown_whatsapp_telegram_mcp_details_404():
    assert client.get("/api/tools/mcp/providers/whatsapp").status_code == 404
    assert client.get("/api/tools/mcp/providers/telegram").status_code == 404


def test_t6_external_provider_status_redacts_tokens(monkeypatch):
    monkeypatch.setenv("WHATSAPP_API_TOKEN", "super-secret-whatsapp-token")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "phone-id")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "super-secret-telegram-token")

    response = client.get("/api/tools/external/providers")

    assert response.status_code == 200
    text = str(response.json())
    assert "super-secret-whatsapp-token" not in text
    assert "super-secret-telegram-token" not in text
    assert "WHATSAPP_API_TOKEN" in text
    assert "TELEGRAM_BOT_TOKEN" in text
