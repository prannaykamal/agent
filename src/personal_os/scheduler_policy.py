from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any

from src.hitl.classifier import classify_tool_risk
from src.personal_os.policy import get_personal_os_policy
from src.tools.registry_types import ApprovalPolicy

DIRECT_LOCAL_READ_TOOLS = {"heartbeat", "list_tasks", "get_agent_status", "restore_checkpoint"}


@dataclass(frozen=True)
class SchedulerPolicyDecision:
    target_tool_id: str
    risk_class: str
    approval_policy: str
    can_execute_directly: bool
    requires_approval: bool
    provider_action_deferred: bool
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return self.__dict__.copy()


def approval_policy_for_target(target_tool_id: str) -> str:
    clean = str(target_tool_id or "").strip()
    personal_policy = get_personal_os_policy(clean)
    if personal_policy is not None:
        return personal_policy.approval_policy.value
    risk, _ = classify_tool_risk(clean)
    if risk == "High":
        return ApprovalPolicy.APPROVAL_REQUIRED.value
    if risk == "Medium":
        return ApprovalPolicy.CONFIRMATION_RECOMMENDED.value
    if risk == "Blocked":
        return ApprovalPolicy.BLOCKED.value
    return ApprovalPolicy.NO_APPROVAL_NEEDED.value


def decide_scheduler_execution(target_tool_id: str, target_payload: Dict[str, Any] | None = None) -> SchedulerPolicyDecision:
    clean = str(target_tool_id or "").strip()
    personal_policy = get_personal_os_policy(clean)
    if personal_policy is not None:
        if clean in DIRECT_LOCAL_READ_TOOLS and personal_policy.allowed:
            return SchedulerPolicyDecision(clean, personal_policy.risk_class.value, personal_policy.approval_policy.value, True, False, False, "Read-only local Personal OS action may execute directly.")
        if personal_policy.approval_policy == ApprovalPolicy.BLOCKED:
            return SchedulerPolicyDecision(clean, personal_policy.risk_class.value, personal_policy.approval_policy.value, False, False, False, personal_policy.reason)
        return SchedulerPolicyDecision(clean, personal_policy.risk_class.value, personal_policy.approval_policy.value, False, True, False, "Scheduled Personal OS write/lifecycle action requires HITL approval before execution.")

    risk, reason = classify_tool_risk(clean)
    if risk == "Blocked":
        return SchedulerPolicyDecision(clean, risk, ApprovalPolicy.BLOCKED.value, False, False, False, reason)
    return SchedulerPolicyDecision(clean, risk, ApprovalPolicy.APPROVAL_REQUIRED.value, False, True, True, "Provider or non-local scheduled tool calls are approval-gated/deferred in T5; provider behavior is not executed by cron.")
