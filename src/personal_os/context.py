from langchain_core.tools import tool


def _deprecated_context_message(tool_name: str) -> str:
    return (
        f"[Personal OS Tool Blocked] '{tool_name}' is deprecated synthetic context management. "
        "Use the approved retrieval and memory context assembly path instead. No context block was written."
    )


@tool
def acquire_context(query_or_topic: str) -> str:
    """Deprecated synthetic context tool retained as a blocked compatibility wrapper."""
    return _deprecated_context_message("acquire_context")


@tool
def release_context(context_id: str) -> str:
    """Deprecated synthetic context tool retained as a blocked compatibility wrapper."""
    return _deprecated_context_message("release_context")
