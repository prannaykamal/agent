from langchain_core.tools import tool
from src.orchestration.registry import update_sub_agent_status, get_sub_agent
from src.orchestration.tools import spawn_agent

@tool
def terminate_agent(agent_id: str) -> str:
    """Forces termination of a running sub-agent process."""
    sub_rec = get_sub_agent(agent_id)
    if not sub_rec:
        return f"[Personal OS Agent Error] Sub-agent '{agent_id}' not found."

    update_sub_agent_status(agent_id=agent_id, status="TERMINATED", result="Force terminated by user request.")
    return f"[Personal OS Agent Terminated] Sub-agent '{agent_id}' has been terminated."

@tool
def pause_agent(agent_id: str) -> str:
    """Pauses execution of an active sub-agent process."""
    sub_rec = get_sub_agent(agent_id)
    if not sub_rec:
        return f"[Personal OS Agent Error] Sub-agent '{agent_id}' not found."

    update_sub_agent_status(agent_id=agent_id, status="PAUSED", result=sub_rec.get("result", ""))
    return f"[Personal OS Agent Paused] Sub-agent '{agent_id}' has been paused."

@tool
def resume_agent(agent_id: str) -> str:
    """Resumes execution of a paused sub-agent process."""
    sub_rec = get_sub_agent(agent_id)
    if not sub_rec:
        return f"[Personal OS Agent Error] Sub-agent '{agent_id}' not found."

    update_sub_agent_status(agent_id=agent_id, status="RUNNING", result=sub_rec.get("result", ""))
    return f"[Personal OS Agent Resumed] Sub-agent '{agent_id}' has been resumed."

@tool
def get_agent_status(agent_id: str) -> str:
    """Retrieves current execution status, role, and output result of a sub-agent."""
    sub_rec = get_sub_agent(agent_id)
    if not sub_rec:
        return f"[Personal OS Agent Error] Sub-agent '{agent_id}' not found."

    return (
        f"[Personal OS Agent Status]\n"
        f"ID: {sub_rec['agent_id']}\n"
        f"Role: {sub_rec['role']}\n"
        f"Status: {sub_rec['status']}\n"
        f"Result: {sub_rec['result'] or '(none)'}"
    )
