from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Mapping, Optional

from src.tools.registry_types import (
    ApprovalPolicy,
    AvailabilityStatus,
    ImplementationType,
    ReadWriteCapability,
    RiskClass,
    ToolMetadata,
)
from src.tools.removed_tools import is_removed_tool_name


class ToolCallerSource(str, Enum):
    CHAT = "chat"
    API = "api"
    SCHEDULER = "scheduler"
    APPROVAL_RESUME = "approval_resume"
    WORKER = "worker"
    MCP_INVOCATION = "mcp_invocation"


class ToolPolicyDecisionType(str, Enum):
    NO_APPROVAL_NEEDED = "no_approval_needed"
    CONFIRMATION_RECOMMENDED = "confirmation_recommended"
    APPROVAL_REQUIRED = "approval_required"
    BLOCKED = "blocked"
    PROVIDER_MANAGED_CONFIRMATION = "provider_managed_confirmation"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class ToolPolicyDecision:
    tool_name: str
    tool_id: str = ""
    provider: str = ""
    implementation_type: str = ""
    decision: ToolPolicyDecisionType = ToolPolicyDecisionType.BLOCKED
    risk_class: RiskClass = RiskClass.BLOCKED
    approval_policy: ApprovalPolicy = ApprovalPolicy.BLOCKED
    read_write_capability: ReadWriteCapability = ReadWriteCapability.UNKNOWN
    reason_code: str = "policy_denied"
    reason: str = "Tool execution denied by policy."
    provider_managed: bool = False
    external_side_effect: bool = False
    destructive: bool = False
    scheduled_capable: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def can_execute_directly(self) -> bool:
        return self.decision in (
            ToolPolicyDecisionType.NO_APPROVAL_NEEDED,
            ToolPolicyDecisionType.CONFIRMATION_RECOMMENDED,
            ToolPolicyDecisionType.PROVIDER_MANAGED_CONFIRMATION,
        )

    @property
    def requires_approval(self) -> bool:
        return self.decision == ToolPolicyDecisionType.APPROVAL_REQUIRED

    @property
    def blocked(self) -> bool:
        return self.decision == ToolPolicyDecisionType.BLOCKED

    @property
    def unavailable(self) -> bool:
        return self.decision == ToolPolicyDecisionType.UNAVAILABLE

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "tool_id": self.tool_id,
            "provider": self.provider,
            "implementation_type": self.implementation_type,
            "decision": self.decision.value,
            "risk_class": self.risk_class.value,
            "approval_policy": self.approval_policy.value,
            "read_write_capability": self.read_write_capability.value,
            "reason_code": self.reason_code,
            "reason": self.reason,
            "provider_managed": self.provider_managed,
            "external_side_effect": self.external_side_effect,
            "destructive": self.destructive,
            "scheduled_capable": self.scheduled_capable,
            "metadata": dict(self.metadata),
        }



_LEGACY_MEDIUM_RISK_REASONS = {
    "schedule_job": "Scheduling: Registers a background recurring job",
    "spawn_agent": "Sub-agent: Launches an autonomous child sub-agent",
}

def _clean_name(tool_name: str) -> str:
    return str(tool_name or "").strip()


def _metadata_for_policy(tool_name: str) -> Optional[ToolMetadata]:
    clean = _clean_name(tool_name)
    try:
        from src.tools.registry import get_tool_metadata_for_policy_by_legacy_name

        return get_tool_metadata_for_policy_by_legacy_name(clean)
    except Exception:
        return None


def _is_sensitive_search_query(arguments: Mapping[str, Any] | None) -> bool:
    if not arguments:
        return False
    query = " ".join(str(arguments.get(key) or "") for key in ("query", "q", "search_query", "input"))
    lowered = query.lower()
    sensitive_markers = (
        "api key",
        "apikey",
        "password",
        "secret",
        "token",
        "credential",
        "private key",
        "ssn",
        "social security",
    )
    return any(marker in lowered for marker in sensitive_markers)


def _approved_context(approval_context: Mapping[str, Any] | None) -> bool:
    if not approval_context:
        return False
    value = approval_context.get("approved")
    return value is True or str(value).upper() == "APPROVED"


def _decision_from_metadata(
    metadata: ToolMetadata,
    *,
    source: ToolCallerSource,
    arguments: Mapping[str, Any] | None,
    approval_context: Mapping[str, Any] | None,
) -> ToolPolicyDecision:
    base = {
        "tool_name": metadata.legacy_name,
        "tool_id": metadata.tool_id,
        "provider": metadata.provider,
        "implementation_type": metadata.implementation_type.value,
        "risk_class": metadata.risk_class,
        "approval_policy": metadata.approval_policy,
        "read_write_capability": metadata.read_write_capability,
        "provider_managed": metadata.provider_managed,
        "external_side_effect": metadata.external_side_effect,
        "destructive": metadata.destructive,
        "scheduled_capable": metadata.scheduled_capable,
        "metadata": {
            "caller_source": source.value,
            "availability_status": metadata.availability_status.value,
        },
    }

    if metadata.implementation_type == ImplementationType.REMOVED or is_removed_tool_name(metadata.legacy_name):
        removed_reason = metadata.removal_reason or "Removed tool is blocked by the tools architecture policy."
        if "removed tool" not in removed_reason.lower():
            removed_reason = f"Removed tool: {removed_reason}"
        return ToolPolicyDecision(
            **base,
            decision=ToolPolicyDecisionType.BLOCKED,
            reason_code="removed_tool",
            reason=removed_reason,
        )

    if source == ToolCallerSource.WORKER:
        return ToolPolicyDecision(
            **base,
            decision=ToolPolicyDecisionType.BLOCKED,
            reason_code="worker_user_tool_forbidden",
            reason="Memory worker and secondary LLM paths cannot invoke user-facing tools.",
        )

    if not metadata.enabled or metadata.availability_status != AvailabilityStatus.AVAILABLE:
        return ToolPolicyDecision(
            **base,
            decision=ToolPolicyDecisionType.UNAVAILABLE,
            reason_code="tool_unavailable",
            reason="Tool is disabled or its provider is unavailable.",
        )

    if metadata.approval_policy == ApprovalPolicy.BLOCKED or metadata.risk_class == RiskClass.BLOCKED:
        return ToolPolicyDecision(
            **base,
            decision=ToolPolicyDecisionType.BLOCKED,
            reason_code="policy_blocked",
            reason="Tool is blocked by unified tool policy.",
        )

    if _is_sensitive_search_query(arguments) and metadata.provider in ("search", "search_tavily", "search_duckduckgo"):
        return ToolPolicyDecision(
            **base,
            decision=ToolPolicyDecisionType.CONFIRMATION_RECOMMENDED,
            reason_code="sensitive_search_confirmation_recommended",
            reason="Search query appears sensitive; confirmation is recommended before external lookup.",
        )

    needs_approval = (
        metadata.approval_policy == ApprovalPolicy.APPROVAL_REQUIRED
        or metadata.risk_class == RiskClass.HIGH
        or metadata.destructive
        or (
            metadata.external_side_effect
            and metadata.read_write_capability in (ReadWriteCapability.WRITE_CAPABLE, ReadWriteCapability.READ_WRITE)
        )
    )
    if needs_approval and not _approved_context(approval_context):
        return ToolPolicyDecision(
            **base,
            decision=ToolPolicyDecisionType.APPROVAL_REQUIRED,
            reason_code="approval_required",
            reason="High-risk, destructive, or external write action requires HITL approval.",
        )

    if metadata.approval_policy == ApprovalPolicy.PROVIDER_MANAGED_CONFIRMATION:
        return ToolPolicyDecision(
            **base,
            decision=ToolPolicyDecisionType.PROVIDER_MANAGED_CONFIRMATION,
            reason_code="provider_managed_confirmation",
            reason="Provider-managed confirmation applies at the MCP provider boundary.",
        )

    if metadata.approval_policy == ApprovalPolicy.CONFIRMATION_RECOMMENDED:
        return ToolPolicyDecision(
            **base,
            decision=ToolPolicyDecisionType.CONFIRMATION_RECOMMENDED,
            reason_code="confirmation_recommended",
            reason="Tool is allowed directly, but confirmation is recommended by policy.",
        )

    return ToolPolicyDecision(
        **base,
        decision=ToolPolicyDecisionType.NO_APPROVAL_NEEDED,
        reason_code="no_approval_needed",
        reason="Read-only or approved low-risk tool may execute directly.",
    )


def evaluate_tool_policy(
    tool_name: str,
    arguments: Mapping[str, Any] | None = None,
    *,
    source: ToolCallerSource | str = ToolCallerSource.CHAT,
    approval_context: Mapping[str, Any] | None = None,
    metadata: ToolMetadata | None = None,
) -> ToolPolicyDecision:
    source_value = ToolCallerSource(source)
    clean = _clean_name(tool_name)
    metadata = metadata or _metadata_for_policy(clean)
    if metadata is None:
        if is_removed_tool_name(clean):
            return ToolPolicyDecision(
                tool_name=clean,
                decision=ToolPolicyDecisionType.BLOCKED,
                risk_class=RiskClass.BLOCKED,
                approval_policy=ApprovalPolicy.BLOCKED,
                reason_code="removed_tool",
                reason="Removed tool is blocked by the tools architecture policy.",
                metadata={"caller_source": source_value.value},
            )
        lower = clean.lower()
        if lower in _LEGACY_MEDIUM_RISK_REASONS:
            return ToolPolicyDecision(
                tool_name=clean,
                decision=ToolPolicyDecisionType.CONFIRMATION_RECOMMENDED,
                risk_class=RiskClass.MEDIUM,
                approval_policy=ApprovalPolicy.CONFIRMATION_RECOMMENDED,
                read_write_capability=ReadWriteCapability.WRITE_CAPABLE,
                reason_code="confirmation_recommended",
                reason=_LEGACY_MEDIUM_RISK_REASONS[lower],
                metadata={"caller_source": source_value.value, "legacy_hitl_demo_tool": True},
            )
        return ToolPolicyDecision(
            tool_name=clean,
            decision=ToolPolicyDecisionType.BLOCKED,
            risk_class=RiskClass.BLOCKED,
            approval_policy=ApprovalPolicy.BLOCKED,
            reason_code="unknown_tool",
            reason="Unknown tool is blocked by default.",
            metadata={"caller_source": source_value.value},
        )
    return _decision_from_metadata(
        metadata,
        source=source_value,
        arguments=arguments,
        approval_context=approval_context,
    )


def classify_tool_policy(
    tool_name: str,
    arguments: Mapping[str, Any] | None = None,
    *,
    source: ToolCallerSource | str = ToolCallerSource.CHAT,
    approval_context: Mapping[str, Any] | None = None,
) -> ToolPolicyDecision:
    return evaluate_tool_policy(
        tool_name,
        arguments,
        source=source,
        approval_context=approval_context,
    )


def legacy_risk_tuple(tool_name: str, arguments: Mapping[str, Any] | None = None) -> tuple[str, str]:
    decision = evaluate_tool_policy(tool_name, arguments, source=ToolCallerSource.CHAT)
    return decision.risk_class.value, decision.reason

