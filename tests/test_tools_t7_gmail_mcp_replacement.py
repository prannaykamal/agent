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


def test_t7_gmail_send_falls_back_to_draft_when_send_is_missing(monkeypatch):
    calls = []

    def fake_invoke(provider_ids, tool_hints, arguments, **_kwargs):
        calls.append(tool_hints)
        if "send" in tool_hints:
            return MCPInvocationResult(status=MCPInvocationStatus.TOOL_UNAVAILABLE, provider_id="gmail")
        return MCPInvocationResult(
            status=MCPInvocationStatus.SUCCEEDED,
            provider_id="gmail",
            tool_name="create_draft",
            content="draft id 1",
        )

    monkeypatch.setattr("src.tools.mcp_invocation.invoke_provider_tool", fake_invoke)
    text = email_send.invoke({"to": "u@example.com", "subject": "s", "body": "b"})
    assert "draft id 1" in text
    assert any("send" in hints for hints in calls)
    assert any("draft" in hints for hints in calls)


def test_t7_chat_does_not_bind_raw_live_gmail_tools(monkeypatch):
    monkeypatch.setattr("src.mcp_gateway.registry._is_tool_provider_available", lambda _name: True)
    from src.mcp_gateway.registry import get_all_mcp_tools

    names = {tool.name for tool in get_all_mcp_tools()}
    assert "gmail_create_draft" not in names
    assert "email_draft" in names
    assert "email_send" in names


def test_t7_enabled_gmail_binds_wrappers_before_discovery(tmp_path, monkeypatch):
    import json

    from src.tools.mcp_provider_registry import clear_mcp_provider_discovery_cache

    config = tmp_path / "mcp_config.json"
    config.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "gmail": {
                        "enabled": True,
                        "transport": "http",
                        "url": "https://gmailmcp.example.test/mcp/v1",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("src.tools.mcp_provider_config.mcp_config_path", lambda: config)
    clear_mcp_provider_discovery_cache()

    from src.mcp_gateway.registry import get_all_mcp_tools

    names = {tool.name for tool in get_all_mcp_tools()}
    assert "email_draft" in names
    assert "email_send" in names
    assert "email_read" in names
    assert "gmail_create_draft" not in names


def test_t7_gmail_unavailable_does_not_fallback_to_smtp_or_imap(monkeypatch):
    monkeypatch.setattr(
        "src.tools.mcp_invocation.invoke_provider_tool",
        lambda *args, **_kwargs: MCPInvocationResult(status=MCPInvocationStatus.PROVIDER_UNAVAILABLE),
    )

    assert "Unavailable" in email_read.invoke({"limit": 1})
    assert "Unavailable" in email_send.invoke({"to": "u@example.com", "subject": "s", "body": "b"})
