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
def isolate_direct_provider_env(monkeypatch):
    for key in _ISOLATED_PROVIDER_ENV:
        monkeypatch.delenv(key, raising=False)
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
