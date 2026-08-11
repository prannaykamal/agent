from typing import List
from langchain_core.tools import BaseTool

from src.personal_os.tasks import create_task, update_task, cancel_task, list_tasks
from src.personal_os.agent_lifecycle import spawn_agent, terminate_agent, pause_agent, resume_agent, get_agent_status
from src.personal_os.scheduling import schedule_job, cancel_job, heartbeat
from src.personal_os.concurrency import lock_resource, unlock_resource
from src.personal_os.event_bus import publish_event
from src.personal_os.checkpointing import checkpoint, restore_checkpoint
from src.personal_os.policy import classify_personal_os_action
from src.tools.registry_types import (
    AvailabilityStatus,
    ImplementationType,
    ToolMetadata,
    normalize_tool_id_part,
    schema_from_langchain_tool,
)

ACTIVE_PERSONAL_OS_TOOLS: List[BaseTool] = [
    create_task, update_task, cancel_task, list_tasks,
    spawn_agent, terminate_agent, pause_agent, resume_agent, get_agent_status,
    schedule_job, cancel_job, heartbeat,
    lock_resource, unlock_resource,
    publish_event,
    checkpoint, restore_checkpoint,
]

ALL_PERSONAL_OS_TOOLS: List[BaseTool] = ACTIVE_PERSONAL_OS_TOOLS


def get_all_personal_os_tools() -> List[BaseTool]:
    """Returns active bounded Personal OS tools for LangChain/LangGraph binding."""
    return list(ACTIVE_PERSONAL_OS_TOOLS)


def get_deprecated_personal_os_tools() -> List[BaseTool]:
    """Deprecated synthetic Personal OS implementations were removed after T4 cleanup."""
    return []


def get_os_tool_catalog() -> List[dict]:
    """Returns catalog metadata for active bounded Personal OS system tools."""
    return [
        {"name": t.name, "description": t.description}
        for t in ACTIVE_PERSONAL_OS_TOOLS
    ]


def _metadata_for_active_tool(tool: BaseTool) -> ToolMetadata:
    policy = classify_personal_os_action(tool.name)
    return ToolMetadata(
        tool_id=f"local.personal_os.{normalize_tool_id_part(tool.name)}",
        legacy_name=tool.name,
        display_name=tool.name.replace("_", " ").title(),
        provider="personal_os",
        category=policy.category,
        implementation_type=ImplementationType.LOCAL,
        enabled=True,
        availability_status=AvailabilityStatus.AVAILABLE,
        risk_class=policy.risk_class,
        approval_policy=policy.approval_policy,
        read_write_capability=policy.read_write_capability,
        external_side_effect=False,
        destructive=policy.destructive,
        scheduled_capable=policy.scheduled_capable,
        provider_managed=False,
        input_schema=schema_from_langchain_tool(tool),
        output_schema_hint="text",
        observability_metadata={
            "migration_phase": "T4",
            "active_legacy_tool": True,
            "registry_source": "src.personal_os.registry",
            "memory_boundary": "read through approved repositories/retrieval only; memory writes must use memory jobs or memory stores",
            "policy_reason": policy.reason,
        },
    )


def get_personal_os_tool_metadata(include_deprecated: bool = False) -> List[ToolMetadata]:
    """Returns metadata for bounded Personal OS tools.

    Deprecated synthetic tool metadata is no longer emitted because their local
    implementations were removed; policy still blocks those legacy names.
    """
    return [_metadata_for_active_tool(tool) for tool in ACTIVE_PERSONAL_OS_TOOLS]
