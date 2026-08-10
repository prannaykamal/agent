from src.mcp_gateway.communication import email_draft, email_read, email_search, email_send
from src.mcp_gateway.registry import get_mcp_tool_risk
from src.tools.mcp_invocation import MCPInvocationResult, MCPInvocationStatus


def test_t7_gmail_tools_use_mcp_boundary(monkeypatch):
    calls = []

    def fake_invoke(provider_ids, tool_hints, arguments, **_kwargs):
        calls.append((provider_ids, tool_hints, arguments))
        return MCPInvocationResult(status=MCPInvocationStatus.SUCCEEDED, provider_id="gmail", tool_name="gmail_tool", content="gmail ok")

    monkeypatch.setattr("src.tools.mcp_invocation.invoke_provider_tool", fake_invoke)

    assert email_read.invoke({"limit": 2}) == "gmail ok"
    assert email_search.invoke({"query": "invoice"}) == "gmail ok"
    assert email_draft.invoke({"to": "u@example.com", "subject": "s", "body": "b"}) == "gmail ok"
    assert email_send.invoke({"to": "u@example.com", "subject": "s", "body": "b"}) == "gmail ok"

    assert all(call[0] == ("gmail",) for call in calls)
    assert any("send" in call[1] for call in calls)


def test_t7_gmail_send_policy_stays_approval_required():
    assert get_mcp_tool_risk("email_send") == "High"


def test_t7_gmail_unavailable_does_not_fallback_to_smtp_or_imap(monkeypatch):
    monkeypatch.setattr(
        "src.tools.mcp_invocation.invoke_provider_tool",
        lambda *args, **_kwargs: MCPInvocationResult(status=MCPInvocationStatus.PROVIDER_UNAVAILABLE),
    )

    assert "Unavailable" in email_read.invoke({"limit": 1})
    assert "Unavailable" in email_send.invoke({"to": "u@example.com", "subject": "s", "body": "b"})
