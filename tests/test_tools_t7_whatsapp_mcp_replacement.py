from src.mcp_gateway.communication import whatsapp_read, whatsapp_send
from src.mcp_gateway.registry import get_mcp_tool_risk
from src.tools.mcp_invocation import MCPInvocationResult, MCPInvocationStatus


def test_t7_whatsapp_read_send_use_mcp_boundary(monkeypatch):
    calls = []

    def fake_invoke(provider_ids, tool_hints, arguments, **_kwargs):
        calls.append((provider_ids, tool_hints, arguments))
        return MCPInvocationResult(status=MCPInvocationStatus.SUCCEEDED, provider_id="whatsapp", tool_name="whatsapp_tool", content="whatsapp ok")

    monkeypatch.setattr("src.tools.mcp_invocation.invoke_provider_tool", fake_invoke)

    assert whatsapp_read.invoke({"limit": 3}) == "whatsapp ok"
    assert whatsapp_send.invoke({"recipient": "+123", "message": "hello"}) == "whatsapp ok"

    assert all(call[0] == ("whatsapp",) for call in calls)
    assert any("send" in call[1] for call in calls)


def test_t7_whatsapp_send_policy_stays_approval_required():
    assert get_mcp_tool_risk("whatsapp_send") == "High"


def test_t7_whatsapp_unavailable_is_safe(monkeypatch):
    monkeypatch.setattr(
        "src.tools.mcp_invocation.invoke_provider_tool",
        lambda *args, **_kwargs: MCPInvocationResult(status=MCPInvocationStatus.PROVIDER_UNAVAILABLE),
    )

    assert "Unavailable" in whatsapp_send.invoke({"recipient": "+123", "message": "hello"})
