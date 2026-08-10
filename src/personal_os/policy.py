from dataclasses import dataclass
from typing import Dict, Optional

from src.tools.registry_types import ApprovalPolicy, ReadWriteCapability, RiskClass


DEPRECATED_SYNTHETIC_TOOLS = {
    "sleep",
    "wake",
    "subscribe_event",
    "acquire_context",
    "release_context",
}


READ_ONLY_ACTIONS = {
    "list_tasks",
    "get_agent_status",
    "heartbeat",
    "restore_checkpoint",
}

LOW_RISK_WRITE_ACTIONS = {
    "create_task",
    "update_task",
    "publish_event",
    "checkpoint",
    "lock_resource",
    "unlock_resource",
}

APPROVAL_REQUIRED_ACTIONS = {
    "cancel_task",
    "spawn_agent",
    "terminate_agent",
    "pause_agent",
    "resume_agent",
    "schedule_job",
    "cancel_job",
}

DESTRUCTIVE_ACTIONS = {
    "cancel_task",
    "terminate_agent",
    "cancel_job",
    "unlock_resource",
}

SCHEDULED_CAPABLE_ACTIONS = {
    "create_task",
    "update_task",
    "cancel_task",
    "schedule_job",
    "cancel_job",
}

TOOL_CATEGORIES: Dict[str, str] = {
    "create_task": "task_state",
    "update_task": "task_state",
    "cancel_task": "task_state",
    "list_tasks": "task_state",
    "spawn_agent": "agent_lifecycle",
    "terminate_agent": "agent_lifecycle",
    "pause_agent": "agent_lifecycle",
    "resume_agent": "agent_lifecycle",
    "get_agent_status": "agent_lifecycle",
    "schedule_job": "scheduler_boundary",
    "cancel_job": "scheduler_boundary",
    "heartbeat": "health",
    "lock_resource": "resource_lock",
    "unlock_resource": "resource_lock",
    "publish_event": "local_event",
    "checkpoint": "checkpoint",
    "restore_checkpoint": "checkpoint",
    "sleep": "deprecated_synthetic",
    "wake": "deprecated_synthetic",
    "subscribe_event": "deprecated_synthetic",
    "acquire_context": "deprecated_synthetic",
    "release_context": "deprecated_synthetic",
}


@dataclass(frozen=True)
class PersonalOSPolicyDecision:
    tool_name: str
    risk_class: RiskClass
    approval_policy: ApprovalPolicy
    read_write_capability: ReadWriteCapability
    category: str
    allowed: bool
    reason: str
    destructive: bool = False
    scheduled_capable: bool = False

    def to_dict(self) -> dict:
        return {
            "tool_name": self.tool_name,
            "risk_class": self.risk_class.value,
            "approval_policy": self.approval_policy.value,
            "read_write_capability": self.read_write_capability.value,
            "category": self.category,
            "allowed": self.allowed,
            "reason": self.reason,
            "destructive": self.destructive,
            "scheduled_capable": self.scheduled_capable,
        }


def is_deprecated_synthetic_tool(tool_name: str) -> bool:
    return str(tool_name or "").strip().lower() in DEPRECATED_SYNTHETIC_TOOLS


def classify_personal_os_action(tool_name: str) -> PersonalOSPolicyDecision:
    clean_name = str(tool_name or "").strip().lower()
    category = TOOL_CATEGORIES.get(clean_name, "personal_os")
    destructive = clean_name in DESTRUCTIVE_ACTIONS
    scheduled_capable = clean_name in SCHEDULED_CAPABLE_ACTIONS

    if clean_name in DEPRECATED_SYNTHETIC_TOOLS:
        return PersonalOSPolicyDecision(
            tool_name=clean_name,
            risk_class=RiskClass.BLOCKED,
            approval_policy=ApprovalPolicy.BLOCKED,
            read_write_capability=ReadWriteCapability.UNKNOWN,
            category=category,
            allowed=False,
            reason="Deprecated synthetic Personal OS tool; use memory retrieval, durable scheduler, or explicit local state tools instead.",
            destructive=destructive,
            scheduled_capable=False,
        )

    if clean_name in READ_ONLY_ACTIONS:
        return PersonalOSPolicyDecision(
            tool_name=clean_name,
            risk_class=RiskClass.LOW,
            approval_policy=ApprovalPolicy.NO_APPROVAL_NEEDED,
            read_write_capability=ReadWriteCapability.READ_ONLY,
            category=category,
            allowed=True,
            reason="Read-only local Personal OS inspection.",
            destructive=False,
            scheduled_capable=scheduled_capable,
        )

    if clean_name in LOW_RISK_WRITE_ACTIONS:
        return PersonalOSPolicyDecision(
            tool_name=clean_name,
            risk_class=RiskClass.MEDIUM,
            approval_policy=ApprovalPolicy.CONFIRMATION_RECOMMENDED,
            read_write_capability=ReadWriteCapability.WRITE_CAPABLE,
            category=category,
            allowed=True,
            reason="Bounded local Personal OS write; audit and idempotency metadata required.",
            destructive=destructive,
            scheduled_capable=scheduled_capable,
        )

    if clean_name in APPROVAL_REQUIRED_ACTIONS:
        return PersonalOSPolicyDecision(
            tool_name=clean_name,
            risk_class=RiskClass.HIGH,
            approval_policy=ApprovalPolicy.APPROVAL_REQUIRED,
            read_write_capability=ReadWriteCapability.WRITE_CAPABLE,
            category=category,
            allowed=True,
            reason="Personal OS lifecycle, destructive, or scheduled boundary action requires approval policy enforcement.",
            destructive=destructive,
            scheduled_capable=scheduled_capable,
        )

    return PersonalOSPolicyDecision(
        tool_name=clean_name,
        risk_class=RiskClass.BLOCKED,
        approval_policy=ApprovalPolicy.BLOCKED,
        read_write_capability=ReadWriteCapability.UNKNOWN,
        category=category,
        allowed=False,
        reason="Unknown Personal OS action is blocked by default.",
        destructive=destructive,
        scheduled_capable=scheduled_capable,
    )


def get_personal_os_policy(tool_name: str) -> Optional[PersonalOSPolicyDecision]:
    clean_name = str(tool_name or "").strip().lower()
    if clean_name not in TOOL_CATEGORIES:
        return None
    return classify_personal_os_action(clean_name)
