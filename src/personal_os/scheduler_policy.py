from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from src.tools.policy import ToolCallerSource, ToolPolicyDecisionType, evaluate_tool_policy
from src.tools.registry_types import ApprovalPolicy
from src.personal_os.policy import LOW_RISK_WRITE_ACTIONS, READ_ONLY_ACTIONS

DIRECT_LOCAL_SCHEDULED_TOOLS = set(READ_ONLY_ACTIONS) | set(LOW_RISK_WRITE_ACTIONS)


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
    decision = evaluate_tool_policy(target_tool_id, {}, source=ToolCallerSource.SCHEDULER)
    if decision.decision == ToolPolicyDecisionType.UNAVAILABLE and decision.risk_class.value == "High":
        return ApprovalPolicy.APPROVAL_REQUIRED.value
    return decision.approval_policy.value


def decide_scheduler_execution(target_tool_id: str, target_payload: Dict[str, Any] | None = None) -> SchedulerPolicyDecision:
    clean = str(target_tool_id or "").strip()
    decision = evaluate_tool_policy(clean, target_payload or {}, source=ToolCallerSource.SCHEDULER)

    if decision.blocked:
        return SchedulerPolicyDecision(
            clean,
            decision.risk_class.value,
            decision.approval_policy.value,
            False,
            False,
            False,
            decision.reason,
        )

    if clean in DIRECT_LOCAL_SCHEDULED_TOOLS and not decision.blocked and not decision.unavailable:
        return SchedulerPolicyDecision(
            clean,
            decision.risk_class.value,
            decision.approval_policy.value,
            True,
            False,
            False,
            "Local Personal OS action may execute when the scheduled time is due.",
        )

    provider_deferred = decision.provider_managed or decision.provider not in ("", "personal_os")
    requires_approval = decision.requires_approval or decision.risk_class.value in ("High", "Medium") or provider_deferred
    approval_policy = ApprovalPolicy.APPROVAL_REQUIRED.value if requires_approval else decision.approval_policy.value
    reason = (
        "Provider or non-local scheduled tool calls are approval-gated/deferred; provider behavior is not executed by cron without policy approval."
        if provider_deferred
        else "Scheduled Personal OS write/lifecycle action requires HITL approval before execution."
    )
    return SchedulerPolicyDecision(
        clean,
        decision.risk_class.value,
        approval_policy,
        False,
        requires_approval,
        provider_deferred,
        reason,
    )