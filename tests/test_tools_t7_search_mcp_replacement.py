import json

from src.mcp_gateway.search import perform_web_search, search_web
from src.tools.mcp_invocation import MCPInvocationResult, MCPInvocationStatus


def test_t7_search_wrapper_invokes_mcp_boundary(monkeypatch):
    calls = []

    def fake_invoke(provider_ids, tool_hints, arguments, **_kwargs):
        calls.append((provider_ids, tool_hints, arguments))
        return MCPInvocationResult(
            status=MCPInvocationStatus.SUCCEEDED,
            provider_id="search_tavily",
            tool_name="tavily_search",
            content=json.dumps({"results": [{"title": "Python", "url": "https://example.com", "snippet": "Result"}]}),
        )

    monkeypatch.setattr("src.tools.mcp_invocation.invoke_provider_tool", fake_invoke)

    text = search_web.invoke({"query": "Python", "max_results": 1})
    results = perform_web_search("Python", max_results=1)

    assert calls[0][0] == ("search_tavily", "search_duckduckgo")
    assert "Source: https://example.com" in text
    assert results == [{"title": "Python", "url": "https://example.com", "snippet": "Result"}]


def test_t7_search_unavailable_has_no_synthetic_fallback(monkeypatch):
    monkeypatch.setattr(
        "src.tools.mcp_invocation.invoke_provider_tool",
        lambda *args, **_kwargs: MCPInvocationResult(status=MCPInvocationStatus.PROVIDER_UNAVAILABLE),
    )

    assert perform_web_search("Python", max_results=2) == []
    assert "Unavailable" in search_web.invoke({"query": "Python"})
