from src.mcp_gateway.communication import telegram_read, telegram_send
from src.mcp_gateway.registry import get_mcp_tool_risk
from src.tools.mcp_invocation import MCPInvocationResult, MCPInvocationStatus


def test_t7_telegram_read_send_use_mcp_boundary(monkeypatch):
    calls = []

    def fake_invoke(provider_ids, tool_hints, arguments, **_kwargs):
        calls.append((provider_ids, tool_hints, arguments))
        return MCPInvocationResult(status=MCPInvocationStatus.SUCCEEDED, provider_id="telegram", tool_name="telegram_tool", content="telegram ok")

    monkeypatch.setattr("src.tools.mcp_invocation.invoke_provider_tool", fake_invoke)

    assert telegram_read.invoke({"limit": 3}) == "telegram ok"
    assert telegram_send.invoke({"chat_id": "chat", "text": "hello"}) == "telegram ok"

    assert all(call[0] == ("telegram",) for call in calls)
    assert any("send" in call[1] for call in calls)


def test_t7_telegram_send_policy_stays_approval_required():
    assert get_mcp_tool_risk("telegram_send") == "High"


def test_t7_telegram_unavailable_is_safe(monkeypatch):
    monkeypatch.setattr(
        "src.tools.mcp_invocation.invoke_provider_tool",
        lambda *args, **_kwargs: MCPInvocationResult(status=MCPInvocationStatus.PROVIDER_UNAVAILABLE),
    )

    assert "Unavailable" in telegram_send.invoke({"chat_id": "chat", "text": "hello"})
