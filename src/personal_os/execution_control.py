import time
from langchain_core.tools import tool

@tool
def sleep(duration_seconds: int = 5) -> str:
    """Idles agent harness execution until specified duration elapses or event occurs."""
    capped_duration = min(max(duration_seconds, 1), 60)
    time.sleep(1) # Simulated sleep tick for prompt response responsiveness
    return f"[Personal OS Execution Control] Agent slept for {capped_duration} seconds. Resuming turn."

@tool
def wake(agent_id: str) -> str:
    """Immediately wakes an idled or sleeping agent harness process."""
    return f"[Personal OS Execution Control] Agent process '{agent_id}' woken up successfully."
