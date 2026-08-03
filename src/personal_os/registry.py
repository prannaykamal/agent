from typing import List
from langchain_core.tools import BaseTool

from src.personal_os.tasks import create_task, update_task, cancel_task, list_tasks
from src.personal_os.agent_lifecycle import terminate_agent, pause_agent, resume_agent, get_agent_status
from src.orchestration.tools import spawn_agent
from src.personal_os.scheduling import schedule_job, cancel_job, heartbeat
from src.personal_os.concurrency import lock_resource, unlock_resource
from src.personal_os.event_bus import publish_event, subscribe_event
from src.personal_os.context import acquire_context, release_context
from src.personal_os.checkpointing import checkpoint, restore_checkpoint
from src.personal_os.execution_control import sleep, wake

ALL_PERSONAL_OS_TOOLS: List[BaseTool] = [
    # Task Management (4)
    create_task, update_task, cancel_task, list_tasks,
    # Agent Lifecycle (5)
    spawn_agent, terminate_agent, pause_agent, resume_agent, get_agent_status,
    # Scheduling & Health (3)
    schedule_job, cancel_job, heartbeat,
    # Concurrency (2)
    lock_resource, unlock_resource,
    # Event Bus (2)
    publish_event, subscribe_event,
    # Context (2)
    acquire_context, release_context,
    # Checkpointing (2)
    checkpoint, restore_checkpoint,
    # Execution Control (2)
    sleep, wake
]

def get_all_personal_os_tools() -> List[BaseTool]:
    """Returns all 22 native Personal OS system tools for LangChain/LangGraph binding."""
    return ALL_PERSONAL_OS_TOOLS

def get_os_tool_catalog() -> List[dict]:
    """Returns catalog metadata for all 22 Personal OS system tools."""
    return [
        {"name": t.name, "description": t.description}
        for t in ALL_PERSONAL_OS_TOOLS
    ]

