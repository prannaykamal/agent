from langchain_core.tools import tool
from src.orchestration.registry import update_sub_agent_status, get_sub_agent
from src.orchestration.sub_agent import execute_sub_agent
from src.personal_os.audit import log_personal_os_action

_TERMINAL_STATUSES = {"COMPLETED", "FAILED", "TERMINATED"}


@tool
def spawn_agent(role: str, instructions: str) -> str:
    """Launches a specialized sub-agent through the bounded Personal OS lifecycle boundary."""
    res = execute_sub_agent(role=role, instructions=instructions)
    agent_id = res.get("agent_id", "")
    log_personal_os_action(
        tool_name="spawn_agent",
        action="PERSONAL_OS_AGENT_SPAWNED",
        payload={"role": role, "instructions": instructions},
        target_resource=agent_id,
    )
    return f"[Sub-Agent '{res['role']}' ({res['agent_id']}) Status: {res['status']}]\nResult: {res['result']}"


@tool
def terminate_agent(agent_id: str) -> str:
    """Marks a running or paused sub-agent as terminated. Completed runs cannot be undone."""
    sub_rec = get_sub_agent(agent_id)
    if not sub_rec:
        return f"[Personal OS Agent Error] Sub-agent '{agent_id}' not found."

    status = str(sub_rec.get("status") or "").upper()
    if status in _TERMINAL_STATUSES:
        return f"[Personal OS Agent Error] Sub-agent '{agent_id}' is already {status.lower()} and cannot be terminated."

    update_sub_agent_status(agent_id=agent_id, status="TERMINATED", result="Force terminated by user request.")
    log_personal_os_action(
        tool_name="terminate_agent",
        action="PERSONAL_OS_AGENT_TERMINATED",
        payload={"agent_id": agent_id},
        target_resource=agent_id,
    )
    return f"[Personal OS Agent Terminated] Sub-agent '{agent_id}' has been terminated."


@tool
def pause_agent(agent_id: str) -> str:
    """Pauses a running sub-agent record so it can be resumed later."""
    sub_rec = get_sub_agent(agent_id)
    if not sub_rec:
        return f"[Personal OS Agent Error] Sub-agent '{agent_id}' not found."

    status = str(sub_rec.get("status") or "").upper()
    if status != "RUNNING":
        return f"[Personal OS Agent Error] Sub-agent '{agent_id}' is {status.lower()} and cannot be paused."

    update_sub_agent_status(agent_id=agent_id, status="PAUSED", result=sub_rec.get("result", ""))
    log_personal_os_action(
        tool_name="pause_agent",
        action="PERSONAL_OS_AGENT_PAUSED",
        payload={"agent_id": agent_id},
        target_resource=agent_id,
    )
    return f"[Personal OS Agent Paused] Sub-agent '{agent_id}' has been paused."


@tool
def resume_agent(agent_id: str) -> str:
    """Resumes a paused sub-agent by re-running its original role and instructions."""
    sub_rec = get_sub_agent(agent_id)
    if not sub_rec:
        return f"[Personal OS Agent Error] Sub-agent '{agent_id}' not found."

    status = str(sub_rec.get("status") or "").upper()
    if status != "PAUSED":
        return f"[Personal OS Agent Error] Sub-agent '{agent_id}' is {status.lower()} and cannot be resumed."

    update_sub_agent_status(agent_id=agent_id, status="RESUMED", result="Re-dispatched original instructions.")
    log_personal_os_action(
        tool_name="resume_agent",
        action="PERSONAL_OS_AGENT_RESUMED",
        payload={"agent_id": agent_id},
        target_resource=agent_id,
    )
    res = execute_sub_agent(
        role=str(sub_rec.get("role") or "assistant"),
        instructions=str(sub_rec.get("instructions") or ""),
        parent_session_id=str(sub_rec.get("parent_session_id") or "main_session"),
    )
    return (
        f"[Personal OS Agent Resumed] Sub-agent '{agent_id}' re-dispatched as '{res['agent_id']}' "
        f"({res['status']}).\nResult: {res['result']}"
    )


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
