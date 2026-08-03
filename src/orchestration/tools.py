from langchain_core.tools import tool
from src.orchestration.sub_agent import execute_sub_agent

@tool
def spawn_agent(role: str, instructions: str) -> str:
    """
    Launches a specialized sub-agent to execute a delegated task in an isolated context.
    
    Args:
        role: The specialized role or persona of the sub-agent (e.g. 'Researcher', 'Coder', 'Summarizer').
        instructions: Clear instructions and task objectives for the sub-agent.
        
    Returns:
        A string summary containing the sub-agent ID, execution status, and task output.
    """
    res = execute_sub_agent(role=role, instructions=instructions)
    return f"[Sub-Agent '{res['role']}' ({res['agent_id']}) Status: {res['status']}]\nResult: {res['result']}"
