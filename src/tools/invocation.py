from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping

from src.tools.errors import ToolErrorCode
from src.tools.policy import ToolCallerSource, ToolPolicyDecision, ToolPolicyDecisionType, evaluate_tool_policy


@dataclass(frozen=True)
class ToolInvocationResult:
    tool_name: str
    status: ToolErrorCode | str
    output: str = ""
    policy_decision: ToolPolicyDecision | None = None
    error: str = ""
    audit_metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return str(self.status) == "SUCCEEDED"

    def to_text(self) -> str:
        if self.ok:
            return self.output
        return self.output or self.error or f"Tool '{self.tool_name}' did not execute."

    def to_dict(self) -> Dict[str, Any]:
        status = self.status.value if hasattr(self.status, "value") else str(self.status)
        return {
            "tool_name": self.tool_name,
            "status": status,
            "output": self.output,
            "error": self.error,
            "policy_decision": self.policy_decision.to_dict() if self.policy_decision else None,
            "audit_metadata": dict(self.audit_metadata),
        }


def _blocked_text(tool_name: str, decision: ToolPolicyDecision) -> str:
    if decision.reason_code == "removed_tool":
        try:
            from src.tools.removed_tools import get_removed_tool_blocked_message

            return get_removed_tool_blocked_message(tool_name)
        except Exception:
            pass
    if decision.unavailable:
        return f"Tool '{tool_name}' is unavailable and was not executed. Reason: {decision.reason}"
    if decision.requires_approval:
        return f"Direct execution of high-risk tool '{tool_name}' blocked. Human-In-The-Loop approval is required."
    return f"Tool '{tool_name}' blocked by policy. Reason: {decision.reason}"


def invoke_registered_tool(
    tool_name: str,
    arguments: Mapping[str, Any] | None,
    tool_map: Mapping[str, Any],
    *,
    source: ToolCallerSource | str = ToolCallerSource.CHAT,
    approval_context: Mapping[str, Any] | None = None,
) -> ToolInvocationResult:
    args = dict(arguments or {})
    decision = evaluate_tool_policy(
        tool_name,
        args,
        source=source,
        approval_context=approval_context,
    )

    if decision.blocked:
        return ToolInvocationResult(
            tool_name=tool_name,
            status=ToolErrorCode.REMOVED_TOOL if decision.reason_code == "removed_tool" else ToolErrorCode.POLICY_DENIED,
            output=_blocked_text(tool_name, decision),
            policy_decision=decision,
        )
    if decision.unavailable:
        return ToolInvocationResult(
            tool_name=tool_name,
            status=ToolErrorCode.PROVIDER_UNAVAILABLE if decision.provider_managed else ToolErrorCode.TOOL_UNAVAILABLE,
            output=_blocked_text(tool_name, decision),
            policy_decision=decision,
        )
    if decision.decision == ToolPolicyDecisionType.APPROVAL_REQUIRED:
        return ToolInvocationResult(
            tool_name=tool_name,
            status=ToolErrorCode.APPROVAL_REQUIRED,
            output=_blocked_text(tool_name, decision),
            policy_decision=decision,
        )

    target_tool = tool_map.get(tool_name)
    if target_tool is None:
        return ToolInvocationResult(
            tool_name=tool_name,
            status=ToolErrorCode.TOOL_UNAVAILABLE,
            output=f"Tool '{tool_name}' is unavailable and was not executed.",
            policy_decision=decision,
        )

    try:
        result = target_tool.invoke(args)
        return ToolInvocationResult(
            tool_name=tool_name,
            status="SUCCEEDED",
            output=str(result),
            policy_decision=decision,
            audit_metadata={
                "policy_decision": decision.decision.value,
                "reason_code": decision.reason_code,
            },
        )
    except Exception as exc:
        return ToolInvocationResult(
            tool_name=tool_name,
            status=ToolErrorCode.INVOCATION_FAILED_TERMINAL,
            output=f"Tool execution error: {str(exc)}",
            error=str(exc)[:500],
            policy_decision=decision,
        )
