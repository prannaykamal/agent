from langchain_core.tools import tool


def _deprecated_execution_control_message(tool_name: str) -> str:
    return (
        f"[Personal OS Tool Blocked] '{tool_name}' is deprecated synthetic execution control. "
        "Use explicit task state, worker controls, or future scheduler behavior instead. No execution occurred."
    )


@tool
def sleep(duration_seconds: int = 5) -> str:
    """Deprecated synthetic execution-control tool retained as a blocked compatibility wrapper."""
    return _deprecated_execution_control_message("sleep")


@tool
def wake(agent_id: str) -> str:
    """Deprecated synthetic execution-control tool retained as a blocked compatibility wrapper."""
    return _deprecated_execution_control_message("wake")
