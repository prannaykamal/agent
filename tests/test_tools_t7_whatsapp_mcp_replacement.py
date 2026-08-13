from src.external_providers.common import ExternalProviderInvocationStatus, ExternalProviderResult
from src.mcp_gateway.communication import whatsapp_read, whatsapp_send
from src.mcp_gateway.registry import get_mcp_tool_risk


def test_t7_whatsapp_read_send_use_direct_api_boundary(monkeypatch):
    calls = []

    def fake_read_status(limit=5):
        calls.append(("read", limit))
        return ExternalProviderResult(status=ExternalProviderInvocationStatus.SUCCEEDED, provider_id="whatsapp_api", content="whatsapp status ok")

    def fake_send_message(recipient, message):
        calls.append(("send", recipient, message))
        return ExternalProviderResult(status=ExternalProviderInvocationStatus.SUCCEEDED, provider_id="whatsapp_api", content="whatsapp send ok")

    monkeypatch.setattr("src.mcp_gateway.communication.whatsapp_api.read_messages", fake_read_status)
    monkeypatch.setattr("src.mcp_gateway.communication.whatsapp_api.send_message", fake_send_message)

    assert whatsapp_read.invoke({"limit": 3}) == "whatsapp status ok"
    assert whatsapp_send.invoke({"recipient": "+123", "message": "hello"}) == "whatsapp send ok"
    assert calls == [("read", 3), ("send", "+123", "hello")]


def test_t7_whatsapp_send_policy_stays_approval_required():
    assert get_mcp_tool_risk("whatsapp_send") == "High"


def test_t7_whatsapp_unavailable_is_safe(monkeypatch):
    def fake_send_message(recipient, message):
        return ExternalProviderResult(status=ExternalProviderInvocationStatus.PROVIDER_UNAVAILABLE, provider_id="whatsapp_api", error="Missing configuration")

    monkeypatch.setattr("src.mcp_gateway.communication.whatsapp_api.send_message", fake_send_message)

    assert "Unavailable" in whatsapp_send.invoke({"recipient": "+123", "message": "hello"})
