import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from src.mcp_gateway.protocol.client import MCPClient
from src.mcp_gateway.protocol.transports.sse import SSEMCPTransport
from src.mcp_gateway.protocol.transports.stdio import StdioMCPTransport
from src.tools.mcp_provider_config import MCPDiscoveryStatus, MCPProviderConfig, MCPTransportType
from src.tools.mcp_provider_registry import (
    MCPClientFactory,
    get_mcp_provider_results,
)
from src.tools.policy import ToolCallerSource, ToolPolicyDecisionType, evaluate_tool_policy
from src.tools.registry_types import ToolMetadata


class MCPInvocationStatus(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    TOOL_UNAVAILABLE = "TOOL_UNAVAILABLE"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    POLICY_DENIED = "POLICY_DENIED"
    REMOVED_TOOL = "REMOVED_TOOL"
    INVOCATION_FAILED_RETRYABLE = "INVOCATION_FAILED_RETRYABLE"
    INVOCATION_FAILED_TERMINAL = "INVOCATION_FAILED_TERMINAL"
    INVOCATION_FAILED = "INVOCATION_FAILED"


@dataclass(frozen=True)
class MCPInvocationRequest:
    provider_ids: Sequence[str]
    tool_hints: Sequence[str]
    arguments: Dict[str, Any] = field(default_factory=dict)
    config_path: Optional[Path] = None


@dataclass(frozen=True)
class MCPInvocationResult:
    status: MCPInvocationStatus
    provider_id: str = ""
    tool_name: str = ""
    content: Any = None
    error: str = ""
    audit_metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == MCPInvocationStatus.SUCCEEDED

    def to_text(self, label: str) -> str:
        if self.ok:
            if isinstance(self.content, str):
                return self.content
            return json.dumps(self.content, sort_keys=True)
        if self.status == MCPInvocationStatus.PROVIDER_UNAVAILABLE:
            return f"[{label} Unavailable]: Provider-managed MCP provider is not configured or unavailable."
        if self.status == MCPInvocationStatus.TOOL_UNAVAILABLE:
            return f"[{label} Unavailable]: Required MCP tool is not available from the configured provider."
        if self.status == MCPInvocationStatus.VALIDATION_ERROR:
            return f"[{label} Validation Error]: {self.error}"
        if self.status == MCPInvocationStatus.APPROVAL_REQUIRED:
            return f"[{label} Approval Required]: {self.error or 'HITL approval is required before this MCP action can execute.'}"
        if self.status in (MCPInvocationStatus.POLICY_DENIED, MCPInvocationStatus.REMOVED_TOOL):
            return f"[{label} Blocked]: {self.error or 'Tool execution was blocked by policy.'}"
        return f"[{label} Invocation Failed]: {self.error or 'MCP provider invocation failed.'}"


def _build_invocation_client(provider: MCPProviderConfig) -> MCPClient:
    if provider.transport_type == MCPTransportType.STDIO:
        if not provider.command:
            raise RuntimeError("Configured stdio MCP provider is missing command.")
        return MCPClient(StdioMCPTransport(command=provider.command, args=provider.args, env=provider.env or None))
    if provider.transport_type == MCPTransportType.SSE:
        if not provider.url:
            raise RuntimeError("Configured SSE MCP provider is missing url.")
        return MCPClient(SSEMCPTransport(url=provider.url))
    raise RuntimeError(f"Unsupported MCP transport for invocation: {provider.transport_type.value}")


def _matches_tool_hint(raw_tool_name: str, hints: Sequence[str]) -> bool:
    name = str(raw_tool_name or "").lower()
    normalized = name.replace("-", "_")
    for hint in hints:
        clean = str(hint or "").strip().lower().replace("-", "_")
        if clean and (clean == normalized or clean in normalized):
            return True
    return False


def _required_keys(input_schema: Any) -> List[str]:
    if isinstance(input_schema, dict) and isinstance(input_schema.get("required"), list):
        return [str(item) for item in input_schema["required"]]
    return []


def _validate_arguments(input_schema: Any, arguments: Dict[str, Any]) -> Optional[str]:
    missing = [key for key in _required_keys(input_schema) if key not in arguments]
    if missing:
        return f"Missing required argument(s): {', '.join(missing)}"
    return None


def _redacted_audit_metadata(provider_id: str, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "provider_id": provider_id,
        "tool_name": tool_name,
        "argument_keys": sorted(str(key) for key in arguments),
        "provider_managed": True,
        "invocation_boundary": "mcp_tools_call",
    }


def _raw_tool_name(metadata: ToolMetadata) -> str:
    return str(metadata.observability_metadata.get("raw_tool_name") or metadata.legacy_name)


def _policy_failure_result(provider_id: str, tool_name: str, decision: Any) -> MCPInvocationResult:
    if decision.decision == ToolPolicyDecisionType.APPROVAL_REQUIRED:
        status = MCPInvocationStatus.APPROVAL_REQUIRED
    elif decision.decision == ToolPolicyDecisionType.BLOCKED and decision.reason_code == "removed_tool":
        status = MCPInvocationStatus.REMOVED_TOOL
    else:
        status = MCPInvocationStatus.POLICY_DENIED
    return MCPInvocationResult(
        status=status,
        provider_id=provider_id,
        tool_name=tool_name,
        error=decision.reason,
        audit_metadata={"policy_decision": decision.to_dict()},
    )


def invoke_mcp_tool(
    provider_id: str,
    tool_name: str,
    arguments: Dict[str, Any],
    *,
    config_path: Optional[Path] = None,
    client_factory: Optional[MCPClientFactory] = None,
    source: ToolCallerSource | str = ToolCallerSource.API,
    approval_context: Optional[Dict[str, Any]] = None,
    metadata: Optional[ToolMetadata] = None,
) -> MCPInvocationResult:
    client = None
    try:
        provider_results = get_mcp_provider_results(config_path=config_path, refresh=True, client_factory=client_factory)
        provider_result = next((result for result in provider_results if result.provider.provider_id == provider_id), None)
        if provider_result is None or provider_result.provider.discovery_status != MCPDiscoveryStatus.DISCOVERED:
            return MCPInvocationResult(status=MCPInvocationStatus.PROVIDER_UNAVAILABLE, provider_id=provider_id)

        metadata = metadata or next(
            (
                item
                for item in provider_result.tools
                if _raw_tool_name(item) == tool_name or item.legacy_name == tool_name
            ),
            None,
        )
        if metadata is not None:
            validation_error = _validate_arguments(metadata.input_schema, arguments)
            if validation_error:
                return MCPInvocationResult(
                    status=MCPInvocationStatus.VALIDATION_ERROR,
                    provider_id=provider_id,
                    tool_name=tool_name,
                    error=validation_error,
                )
            policy = evaluate_tool_policy(
                metadata.legacy_name,
                arguments,
                source=source,
                approval_context=approval_context,
                metadata=metadata,
            )
            if policy.blocked or policy.requires_approval:
                return _policy_failure_result(provider_id, tool_name, policy)
        else:
            return MCPInvocationResult(status=MCPInvocationStatus.TOOL_UNAVAILABLE, provider_id=provider_id, tool_name=tool_name)

        client = client_factory(provider_result.provider) if client_factory else _build_invocation_client(provider_result.provider)
        content = client.call_tool(name=tool_name, arguments=arguments)
        return MCPInvocationResult(
            status=MCPInvocationStatus.SUCCEEDED,
            provider_id=provider_id,
            tool_name=tool_name,
            content=content,
            audit_metadata=_redacted_audit_metadata(provider_id, tool_name, arguments),
        )
    except Exception as exc:
        return MCPInvocationResult(
            status=MCPInvocationStatus.INVOCATION_FAILED_TERMINAL,
            provider_id=provider_id,
            tool_name=tool_name,
            error=str(exc)[:240],
        )
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass


def invoke_provider_tool(
    provider_ids: Sequence[str],
    tool_hints: Sequence[str],
    arguments: Dict[str, Any],
    *,
    config_path: Optional[Path] = None,
    client_factory: Optional[MCPClientFactory] = None,
    source: ToolCallerSource | str = ToolCallerSource.API,
    approval_context: Optional[Dict[str, Any]] = None,
) -> MCPInvocationResult:
    results = get_mcp_provider_results(config_path=config_path, refresh=True, client_factory=client_factory)
    for provider_id in provider_ids:
        provider_result = next((result for result in results if result.provider.provider_id == provider_id), None)
        if provider_result is None or provider_result.provider.discovery_status != MCPDiscoveryStatus.DISCOVERED:
            continue
        for metadata in provider_result.tools:
            raw_tool_name = _raw_tool_name(metadata)
            if not _matches_tool_hint(raw_tool_name, tool_hints):
                continue
            validation_error = _validate_arguments(metadata.input_schema, arguments)
            if validation_error:
                return MCPInvocationResult(
                    status=MCPInvocationStatus.VALIDATION_ERROR,
                    provider_id=provider_id,
                    tool_name=raw_tool_name,
                    error=validation_error,
                )
            policy = evaluate_tool_policy(
                metadata.legacy_name,
                arguments,
                source=source,
                approval_context=approval_context,
                metadata=metadata,
            )
            if policy.blocked or policy.requires_approval:
                return _policy_failure_result(provider_id, raw_tool_name, policy)
            return invoke_mcp_tool(
                provider_id,
                raw_tool_name,
                arguments,
                config_path=config_path,
                client_factory=client_factory,
                source=source,
                approval_context=approval_context,
                metadata=metadata,
            )

    configured_provider = next((result for result in results if result.provider.provider_id in provider_ids and result.provider.is_configured), None)
    if configured_provider:
        return MCPInvocationResult(
            status=MCPInvocationStatus.TOOL_UNAVAILABLE,
            provider_id=configured_provider.provider.provider_id,
        )
    return MCPInvocationResult(status=MCPInvocationStatus.PROVIDER_UNAVAILABLE)