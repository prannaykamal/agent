import json
from typing import Any, Dict, List

from langchain_core.tools import tool

from src.tools import mcp_invocation

_SEARCH_PROVIDERS = ("search_tavily", "search_duckduckgo")
_SEARCH_TOOL_HINTS = ("search", "query")


def _coerce_search_results(content: Any, max_results: int) -> List[Dict[str, str]]:
    data = content
    if isinstance(content, str):
        try:
            data = json.loads(content)
        except Exception:
            return [{"title": "MCP Search Result", "url": "", "snippet": content[:500]}][:max_results]
    if isinstance(data, dict):
        data = data.get("results") or data.get("items") or data.get("content") or []
    if not isinstance(data, list):
        return []
    results: List[Dict[str, str]] = []
    for item in data[:max_results]:
        if isinstance(item, dict):
            results.append({
                "title": str(item.get("title") or item.get("name") or "MCP Search Result"),
                "url": str(item.get("url") or item.get("link") or item.get("href") or ""),
                "snippet": str(item.get("snippet") or item.get("content") or item.get("body") or ""),
            })
        else:
            results.append({"title": "MCP Search Result", "url": "", "snippet": str(item)[:500]})
    return results


def perform_web_search(query: str, max_results: int = 3) -> List[Dict[str, str]]:
    """Compatibility wrapper that invokes provider-managed search MCP tools only."""
    cleaned = query.strip()
    if not cleaned:
        return []
    result = mcp_invocation.invoke_provider_tool(
        provider_ids=_SEARCH_PROVIDERS,
        tool_hints=_SEARCH_TOOL_HINTS,
        arguments={"query": cleaned, "max_results": max_results},
    )
    if not result.ok:
        return []
    return _coerce_search_results(result.content, max_results)


@tool
def search_web(query: str, max_results: int = 3) -> str:
    """Performs web search through a configured provider-managed MCP search tool."""
    cleaned = query.strip()
    if not cleaned:
        return "[Web Search Error]: Empty query provided."

    result = mcp_invocation.invoke_provider_tool(
        provider_ids=_SEARCH_PROVIDERS,
        tool_hints=_SEARCH_TOOL_HINTS,
        arguments={"query": cleaned, "max_results": max_results},
    )
    if not result.ok:
        return result.to_text("Web Search MCP")

    results = _coerce_search_results(result.content, max_results)
    if not results:
        return f"[Web Search Results for '{cleaned}']: No results found."

    formatted = []
    for idx, item in enumerate(results, start=1):
        formatted.append(f"{idx}. {item['title']} - {item['snippet']}\n   Source: {item['url']}")
    return f"[MCP Web Search Results for '{cleaned}']\n" + "\n".join(formatted)
