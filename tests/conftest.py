"""Shared pytest isolation so local .env secrets cannot leak into the suite."""

import pytest

# Direct-provider secrets must not make Telegram/WhatsApp look configured during
# default unit tests. Tests that need a token call monkeypatch.setenv themselves.
_ISOLATED_PROVIDER_ENV = (
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_TEST_CHAT_ID",
    "WHATSAPP_API_TOKEN",
    "WHATSAPP_PHONE_NUMBER_ID",
)


@pytest.fixture(autouse=True)
def isolate_direct_provider_env(monkeypatch, tmp_path_factory):
    for key in _ISOLATED_PROVIDER_ENV:
        monkeypatch.delenv(key, raising=False)
    missing_mcp = tmp_path_factory.mktemp("isolated_mcp") / "mcp_config.json"
    monkeypatch.setattr("src.tools.mcp_provider_config.mcp_config_path", lambda: missing_mcp)
    monkeypatch.setattr("src.mcp_gateway.mcp_bridge.MCP_CONFIG_PATH", missing_mcp)
    try:
        monkeypatch.setattr("src.tools.provider_config.mcp_config_path", lambda: missing_mcp)
    except Exception:
        pass
    try:
        from src.tools.mcp_provider_registry import clear_mcp_provider_discovery_cache

        clear_mcp_provider_discovery_cache()
    except Exception:
        pass
    yield
    try:
        from src.tools.mcp_provider_registry import clear_mcp_provider_discovery_cache

        clear_mcp_provider_discovery_cache()
    except Exception:
        pass
