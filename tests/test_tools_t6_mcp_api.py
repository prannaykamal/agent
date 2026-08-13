import json

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


def test_t6_api_tools_shape_remains_compatible_with_external_api_bucket():
    response = client.get("/api/tools")

    assert response.status_code == 200
    data = response.json()
    assert set(data) == {"total_tools", "personal_os_tools", "mcp_tools", "external_api_tools"}
    assert isinstance(data["personal_os_tools"], list)
    assert isinstance(data["mcp_tools"], list)
    assert isinstance(data["external_api_tools"], list)


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


def test_t6_live_mcp_bridge_skips_stale_whatsapp_telegram_config(tmp_path, monkeypatch, capsys):
    from src.mcp_gateway.mcp_bridge import load_live_mcp_tools

    config_path = tmp_path / "mcp_config.json"
    config_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "whatsapp": {"transport": "stdio", "command": "whatsapp-cmd"},
                    "telegram": {"transport": "stdio", "command": "telegram-cmd"},
                    "gmail": {"transport": "stdio", "command": "gmail-cmd"},
                }
            }
        ),
        encoding="utf-8",
    )
    attempts = []

    class FakeTransport:
        def __init__(self, command, args=None, env=None, cwd=None):
            self.command = command

    class FakeClient:
        def __init__(self, transport):
            attempts.append(transport.command)

        def list_tools(self):
            return []

    monkeypatch.setattr("src.mcp_gateway.protocol.factory.StdioMCPTransport", FakeTransport)
    monkeypatch.setattr("src.mcp_gateway.protocol.factory.MCPClient", FakeClient)

    assert load_live_mcp_tools(config_path) == []
    assert attempts == ["gmail-cmd"]
    captured = capsys.readouterr()
    assert "server 'whatsapp'" not in captured.out
    assert "server 'telegram'" not in captured.out


def test_t6_direct_api_tools_are_not_in_mcp_tools_bucket(monkeypatch):
    monkeypatch.setenv("WHATSAPP_API_TOKEN", "fake-whatsapp-token")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "phone-id")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-telegram-token")

    response = client.get("/api/tools")

    assert response.status_code == 200
    data = response.json()
    mcp_names = {item["name"] for item in data["mcp_tools"]}
    external_names = {item["name"] for item in data["external_api_tools"]}
    direct_names = {"whatsapp_read", "whatsapp_send", "telegram_read", "telegram_send"}
    assert mcp_names.isdisjoint(direct_names)
    assert direct_names.issubset(external_names)


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


def test_t6_direct_provider_invocation_errors_redact_secret_values(monkeypatch):
    from src.external_providers import telegram_bot_api, whatsapp_api

    telegram_token = "123456:telegram-secret-value"
    whatsapp_token = "whatsapp-secret-value"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", telegram_token)
    monkeypatch.setenv("WHATSAPP_API_TOKEN", whatsapp_token)
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "phone-id")

    def fake_urlopen(request, timeout=20):
        full_url = getattr(request, "full_url", "")
        auth = request.headers.get("Authorization", "")
        raise RuntimeError(f"failed url={full_url} auth={auth}")

    monkeypatch.setattr("src.external_providers.common.urllib.request.urlopen", fake_urlopen)

    telegram_result = telegram_bot_api.send_message(chat_id="chat", text="hello")
    whatsapp_result = whatsapp_api.send_message(recipient="+123", message="hello")
    combined = f"{telegram_result.to_text('Telegram')} {telegram_result.to_dict()} {whatsapp_result.to_text('WhatsApp')} {whatsapp_result.to_dict()}"

    assert telegram_token not in combined
    assert whatsapp_token not in combined
    assert "[REDACTED]" in combined


def test_provider_config_get_redacts_saved_values(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text("WHATSAPP_API_TOKEN=raw-whatsapp-token\nWHATSAPP_PHONE_NUMBER_ID=phone-id\nTELEGRAM_BOT_TOKEN=raw-telegram-token\n", encoding="utf-8")
    monkeypatch.setattr("src.tools.provider_config._ENV_PATH", env_path)
    monkeypatch.delenv("WHATSAPP_API_TOKEN", raising=False)
    monkeypatch.delenv("WHATSAPP_PHONE_NUMBER_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

    response = client.get("/api/config/providers")

    assert response.status_code == 200
    body = response.json()
    text = str(body)
    provider_types = {item["provider_id"]: item["provider_type"] for item in body["providers"]}
    assert provider_types["gmail"] == "mcp"
    assert provider_types["google_calendar"] == "mcp"
    assert provider_types["search_tavily"] == "mcp"
    assert provider_types["whatsapp_api"] == "external_api"
    assert provider_types["telegram_bot_api"] == "external_api"
    assert "raw-whatsapp-token" not in text
    assert "raw-telegram-token" not in text
    assert "[REDACTED]" in text


def test_provider_config_post_external_stores_without_returning_raw_secret(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    monkeypatch.setattr("src.tools.provider_config._ENV_PATH", env_path)
    monkeypatch.delenv("WHATSAPP_API_TOKEN", raising=False)
    monkeypatch.delenv("WHATSAPP_PHONE_NUMBER_ID", raising=False)

    response = client.post(
        "/api/config/providers/whatsapp_api",
        json={"values": {"WHATSAPP_API_TOKEN": "saved-whatsapp-token", "WHATSAPP_PHONE_NUMBER_ID": "phone-id"}},
    )

    assert response.status_code == 200
    text = str(response.json())
    assert "saved-whatsapp-token" not in text
    assert "[REDACTED]" in text
    assert "saved-whatsapp-token" in env_path.read_text(encoding="utf-8")


def test_provider_config_validate_external_is_status_only(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    monkeypatch.setattr("src.tools.provider_config._ENV_PATH", env_path)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "validate-telegram-token")

    def forbidden_send(*args, **kwargs):
        raise AssertionError("validation must not send messages")

    monkeypatch.setattr("src.external_providers.telegram_bot_api.send_message", forbidden_send)

    response = client.post("/api/config/providers/telegram_bot_api/validate")

    assert response.status_code == 200
    text = str(response.json())
    assert "validate-telegram-token" not in text
    assert response.json()["provider_type"] == "external_api"


def test_provider_config_validate_mcp_uses_safe_status_refresh(monkeypatch):
    calls = []

    def fake_get_status(provider_id, refresh=False, include_config=False):
        calls.append({"provider_id": provider_id, "refresh": refresh, "include_config": include_config})
        return {
            "provider_id": provider_id,
            "configured": True,
            "availability_status": "available",
            "discovery_status": "discovered",
            "last_error": None,
        }

    monkeypatch.setattr("src.tools.provider_config.get_mcp_provider_status", fake_get_status)

    response = client.post("/api/config/providers/gmail/validate")

    assert response.status_code == 200
    assert response.json()["provider_type"] == "mcp"
    assert {"provider_id": "gmail", "refresh": True, "include_config": False} in calls


def test_provider_config_clear_secret_removes_external_secret(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text("TELEGRAM_BOT_TOKEN=clear-me\nTELEGRAM_TEST_CHAT_ID=123\n", encoding="utf-8")
    monkeypatch.setattr("src.tools.provider_config._ENV_PATH", env_path)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "clear-me")

    response = client.delete("/api/config/providers/telegram_bot_api/secret")

    assert response.status_code == 200
    text = env_path.read_text(encoding="utf-8")
    assert "TELEGRAM_BOT_TOKEN" not in text
    assert "clear-me" not in str(response.json())

def test_provider_config_mcp_errors_redact_marker_free_configured_values(tmp_path, monkeypatch):
    from src.tools.mcp_provider_registry import clear_mcp_provider_discovery_cache

    secrets = {
        "gmail": "gmail_plain_value_ABC123_NO_MARKER",
        "google_calendar": "calendar_plain_value_ABC123_NO_MARKER",
        "search_tavily": "search_plain_value_ABC123_NO_MARKER",
    }
    config_path = tmp_path / "mcp_config.json"
    config_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "gmail": {
                        "enabled": True,
                        "transport": "stdio",
                        "command": "fake-gmail",
                        "env": {"GMAIL_AUTH": secrets["gmail"]},
                    },
                    "google_calendar": {
                        "enabled": True,
                        "transport": "stdio",
                        "command": "fake-calendar",
                        "oauth": {"clientSecret": secrets["google_calendar"]},
                    },
                    "search_tavily": {
                        "enabled": True,
                        "transport": "stdio",
                        "command": "fake-search",
                        "env": {"TAVILY_API_KEY": secrets["search_tavily"]},
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("src.tools.mcp_provider_config.mcp_config_path", lambda: config_path)
    clear_mcp_provider_discovery_cache()

    class FakeClient:
        def __init__(self, provider):
            self.provider = provider

        def list_tools(self):
            raise RuntimeError(f"provider echoed {secrets[self.provider.provider_id]} during discovery")

    monkeypatch.setattr("src.tools.mcp_provider_registry._build_mcp_client", lambda provider: FakeClient(provider))

    for provider_id, raw_secret in secrets.items():
        validate_response = client.post(f"/api/config/providers/{provider_id}/validate")
        assert validate_response.status_code == 200
        validate_text = json.dumps(validate_response.json(), sort_keys=True)
        assert raw_secret not in validate_text
        assert "provider echoed" in validate_text
        assert "[REDACTED]" in validate_text

        config_response = client.get("/api/config/providers")
        assert config_response.status_code == 200
        config_text = json.dumps(config_response.json(), sort_keys=True)
        assert raw_secret not in config_text

        status_response = client.get(f"/api/tools/mcp/providers/{provider_id}")
        assert status_response.status_code == 200
        status_text = json.dumps(status_response.json(), sort_keys=True)
        assert raw_secret not in status_text

    overview_response = client.get("/api/tools/observability/overview")
    assert overview_response.status_code == 200
    overview_text = json.dumps(overview_response.json(), sort_keys=True)
    for raw_secret in secrets.values():
        assert raw_secret not in overview_text


def test_t6_live_mcp_bridge_redacts_marker_free_configured_secret_in_warning(tmp_path, monkeypatch, capsys):
    from src.mcp_gateway.mcp_bridge import load_live_mcp_tools

    raw_secret = "gmail_plain_value_ABC123_NO_MARKER"
    config_path = tmp_path / "mcp_config.json"
    config_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "gmail": {
                        "transport": "stdio",
                        "command": "gmail-cmd",
                        "env": {"GMAIL_AUTH": raw_secret},
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    class FakeTransport:
        def __init__(self, command, args=None, env=None, cwd=None):
            self.command = command

    class FakeClient:
        def __init__(self, transport):
            self.transport = transport

        def list_tools(self):
            raise RuntimeError(f"bridge echoed {raw_secret}")

    monkeypatch.setattr("src.mcp_gateway.protocol.factory.StdioMCPTransport", FakeTransport)
    monkeypatch.setattr("src.mcp_gateway.protocol.factory.MCPClient", FakeClient)

    assert load_live_mcp_tools(config_path) == []
    captured = capsys.readouterr()
    assert raw_secret not in captured.out
    assert "bridge echoed" in captured.out
    assert "[REDACTED]" in captured.out


def test_t6_mcp_invocation_errors_redact_marker_free_configured_secret(tmp_path):
    from src.tools.mcp_invocation import invoke_mcp_tool
    from src.tools.mcp_provider_registry import clear_mcp_provider_discovery_cache

    raw_secret = "gmail_plain_value_ABC123_NO_MARKER"
    config_path = tmp_path / "mcp_config.json"
    config_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "gmail": {
                        "enabled": True,
                        "transport": "stdio",
                        "command": "fake-gmail",
                        "env": {"GMAIL_AUTH": raw_secret},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    clear_mcp_provider_discovery_cache()

    class FakeClient:
        def __init__(self, provider):
            self.provider = provider

        def list_tools(self):
            return [{"name": "read", "description": "Read Gmail", "inputSchema": {"type": "object", "properties": {}}}]

        def call_tool(self, name, arguments):
            raise RuntimeError(f"tools call echoed {raw_secret}")

    result = invoke_mcp_tool(
        "gmail",
        "read",
        {},
        config_path=config_path,
        client_factory=lambda provider: FakeClient(provider),
    )

    result_text = result.to_text("Gmail MCP")
    assert raw_secret not in result.error
    assert raw_secret not in result_text
    assert "tools call echoed" in result.error
    assert "[REDACTED]" in result.error
