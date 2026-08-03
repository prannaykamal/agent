from langchain_core.tools import tool
from src.mcp_gateway.search_adapters import perform_web_search

@tool
def search_web(query: str, max_results: int = 3) -> str:
    """
    Performs a web search for a given query and returns top web snippets with title and URL citations.
    
    Args:
        query: Search keywords or question.
        max_results: Maximum number of search results to return.
        
    Returns:
        Structured text containing titles, snippets, and source URL citations.
    """
    cleaned = query.strip()
    if not cleaned:
        return "[Web Search Error]: Empty query provided."

    results = perform_web_search(cleaned, max_results=max_results)
    if not results:
        return f"[Web Search Results for '{cleaned}']: No results found."

    formatted_list = []
    for idx, r in enumerate(results, start=1):
        title = r.get("title", "Web Result")
        snippet = r.get("snippet", "Snippet unavailable")
        url = r.get("url", "#")
        formatted_list.append(f"{idx}. {title} - {snippet}\n   Source: {url}")

    return f"[Live Web Search Results for '{cleaned}']\n" + "\n".join(formatted_list)
