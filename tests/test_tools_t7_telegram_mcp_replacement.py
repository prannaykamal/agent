from src.external_providers.common import ExternalProviderInvocationStatus, ExternalProviderResult
from src.mcp_gateway.communication import telegram_read, telegram_send
from src.mcp_gateway.registry import get_mcp_tool_risk


def test_t7_telegram_read_send_use_direct_api_boundary(monkeypatch):
    calls = []

    def fake_read_status(limit=5):
        calls.append(("read", limit))
        return ExternalProviderResult(status=ExternalProviderInvocationStatus.SUCCEEDED, provider_id="telegram_bot_api", content="telegram status ok")

    def fake_send_message(chat_id, text):
        calls.append(("send", chat_id, text))
        return ExternalProviderResult(status=ExternalProviderInvocationStatus.SUCCEEDED, provider_id="telegram_bot_api", content="telegram send ok")

    monkeypatch.setattr("src.mcp_gateway.communication.telegram_bot_api.read_messages", fake_read_status)
    monkeypatch.setattr("src.mcp_gateway.communication.telegram_bot_api.send_message", fake_send_message)

    assert telegram_read.invoke({"limit": 3}) == "telegram status ok"
    assert telegram_send.invoke({"chat_id": "chat", "text": "hello"}) == "telegram send ok"
    assert calls == [("read", 3), ("send", "chat", "hello")]


def test_t7_telegram_send_policy_stays_approval_required():
    assert get_mcp_tool_risk("telegram_send") == "High"


def test_t7_telegram_unavailable_is_safe(monkeypatch):
    def fake_send_message(chat_id, text):
        return ExternalProviderResult(status=ExternalProviderInvocationStatus.PROVIDER_UNAVAILABLE, provider_id="telegram_bot_api", error="Missing configuration")

    monkeypatch.setattr("src.mcp_gateway.communication.telegram_bot_api.send_message", fake_send_message)

    assert "Unavailable" in telegram_send.invoke({"chat_id": "chat", "text": "hello"})
