from typing import Dict, List
from langchain_core.tools import BaseTool

from src.hitl.classifier import classify_tool_risk
from src.personal_os.tasks import create_task, update_task, cancel_task, list_tasks
from src.personal_os.agent_lifecycle import terminate_agent, pause_agent, resume_agent, get_agent_status
from src.orchestration.tools import spawn_agent
from src.personal_os.scheduling import schedule_job, cancel_job, heartbeat
from src.personal_os.concurrency import lock_resource, unlock_resource
from src.personal_os.event_bus import publish_event, subscribe_event
from src.personal_os.context import acquire_context, release_context
from src.personal_os.checkpointing import checkpoint, restore_checkpoint
from src.personal_os.execution_control import sleep, wake
from src.tools.registry_types import (
    AvailabilityStatus,
    ImplementationType,
    ToolMetadata,
    approval_policy_for_risk,
    infer_read_write_capability,
    normalize_tool_id_part,
    schema_from_langchain_tool,
)

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

_PERSONAL_OS_TOOL_CATEGORIES: Dict[str, str] = {
    "create_task": "task",
    "update_task": "task",
    "cancel_task": "task",
    "list_tasks": "task",
    "spawn_agent": "agent_lifecycle",
    "terminate_agent": "agent_lifecycle",
    "pause_agent": "agent_lifecycle",
    "resume_agent": "agent_lifecycle",
    "get_agent_status": "agent_lifecycle",
    "schedule_job": "scheduling",
    "cancel_job": "scheduling",
    "heartbeat": "health",
    "lock_resource": "resource_lock",
    "unlock_resource": "resource_lock",
    "publish_event": "event_bus",
    "subscribe_event": "event_bus",
    "acquire_context": "context",
    "release_context": "context",
    "checkpoint": "checkpoint",
    "restore_checkpoint": "checkpoint",
    "sleep": "execution_control",
    "wake": "execution_control",
}


def get_personal_os_tool_metadata() -> List[ToolMetadata]:
    """Returns T1 metadata for current Personal OS tools without changing behavior."""
    metadata: List[ToolMetadata] = []
    for tool in ALL_PERSONAL_OS_TOOLS:
        risk_class, _ = classify_tool_risk(tool.name)
        category = _PERSONAL_OS_TOOL_CATEGORIES.get(tool.name, "personal_os")
        metadata.append(
            ToolMetadata(
                tool_id=f"local.personal_os.{normalize_tool_id_part(tool.name)}",
                legacy_name=tool.name,
                display_name=tool.name.replace("_", " ").title(),
                provider="personal_os",
                category=category,
                implementation_type=ImplementationType.LOCAL,
                enabled=True,
                availability_status=AvailabilityStatus.AVAILABLE,
                risk_class=risk_class,
                approval_policy=approval_policy_for_risk(risk_class),
                read_write_capability=infer_read_write_capability(tool.name),
                external_side_effect=False,
                destructive=tool.name in {"cancel_task", "terminate_agent", "unlock_resource"},
                scheduled_capable=tool.name not in {"heartbeat", "sleep", "wake"},
                provider_managed=False,
                input_schema=schema_from_langchain_tool(tool),
                output_schema_hint="text",
                observability_metadata={
                    "migration_phase": "T1",
                    "active_legacy_tool": True,
                    "registry_source": "src.personal_os.registry",
                },
            )
        )
    return metadata

