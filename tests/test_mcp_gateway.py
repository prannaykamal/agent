import pytest
from src.mcp_gateway.communication import (
    email_read, email_search, email_draft, email_send,
    whatsapp_read, whatsapp_send,
    telegram_read, telegram_send
)
from src.mcp_gateway.calendar import (
    calendar_inspect_availability, calendar_propose_event, calendar_create_event
)
from src.mcp_gateway.search import search_web
from src.mcp_gateway.sandboxes.code_sandbox import (
    run_code, github_clone, github_commit_and_push, github_merge
)
from src.mcp_gateway.sandboxes.browser_sandbox import safe_browse_url, sanitize_html_to_markdown
from src.mcp_gateway.registry import get_all_mcp_tools, get_mcp_tool_risk

def test_communication_mcp_tools():
    read_res = email_read.invoke({"limit": 2})
    assert "[Email MCP]" in read_res

    search_res = email_search.invoke({"query": "invoice"})
    assert "invoice" in search_res

    draft_res = email_draft.invoke({"to": "user@example.com", "subject": "Test", "body": "Draft body"})
    assert "Draft Saved" in draft_res

    send_res = email_send.invoke({"to": "user@example.com", "subject": "Test", "body": "Send body"})
    assert "SENT" in send_res

    wa_res = whatsapp_send.invoke({"recipient": "+1234567890", "message": "Hello"})
    assert "WhatsApp MCP" in wa_res

    tg_res = telegram_send.invoke({"chat_id": "12345", "text": "Ping"})
    assert "Telegram MCP" in tg_res

def test_calendar_mcp_tools():
    avail_res = calendar_inspect_availability.invoke({"start_date": "2026-08-01", "end_date": "2026-08-02"})
    assert "Calendar MCP" in avail_res

    prop_res = calendar_propose_event.invoke({"title": "Design Review", "start_time": "10:00", "end_time": "11:00"})
    assert "PROPOSAL" in prop_res

    create_res = calendar_create_event.invoke({"title": "Design Review", "start_time": "10:00", "end_time": "11:00"})
    assert "CREATED" in create_res

def test_search_mcp_tool():
    search_res = search_web.invoke({"query": "Python 3.12 features"})
    assert "Web Search Results" in search_res
    assert "https://" in search_res

def test_code_sandbox():
    python_code = "print(2 + 2)"
    run_res = run_code.invoke({"code": python_code, "language": "python"})
    assert "[Code Sandbox Output - Exit Code: 0]" in run_res
    assert "4" in run_res

    clone_res = github_clone.invoke({"repo_url": "https://github.com/example/repo.git"})
    assert "status" in clone_res or "GitHub" in clone_res

    merge_res = github_merge.invoke({"source_branch": "feature/ai", "target_branch": "main"})
    assert "status" in merge_res or "GitHub" in merge_res


def test_browser_sandbox():
    html_sample = "<html><body><h1>Test Title</h1><script>alert('bad');</script><p>Hello World</p></body></html>"
    clean_md = sanitize_html_to_markdown(html_sample)
    assert "alert" not in clean_md
    assert "Test Title" in clean_md
    assert "Hello World" in clean_md

    browse_res = safe_browse_url.invoke({"url": "https://example.com/docs"})
    assert "[Browser Sandbox Content" in browse_res
    assert "https://example.com/docs" in browse_res

def test_mcp_registry_and_risk():
    all_tools = get_all_mcp_tools()
    assert len(all_tools) >= 15

    tool_names = [t.name for t in all_tools]
    assert "email_send" in tool_names
    assert "calendar_create_event" in tool_names
    assert "search_web" in tool_names
    assert "run_code" in tool_names

    assert get_mcp_tool_risk("email_send") == "High"
    assert get_mcp_tool_risk("whatsapp_send") == "High"
    assert get_mcp_tool_risk("calendar_create_event") == "High"
    assert get_mcp_tool_risk("github_merge") == "High"
    assert get_mcp_tool_risk("search_web") == "Low"
    assert get_mcp_tool_risk("run_code") == "Low"
