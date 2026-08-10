from typing import Any, Dict, Tuple

from src.tools.registry_types import (
    ApprovalPolicy,
    AvailabilityStatus,
    ImplementationType,
    ReadWriteCapability,
    RiskClass,
    ToolMetadata,
    normalize_tool_id_part,
)
from src.tools.mcp_provider_config import MCPDiscoveryStatus, MCPProviderConfig


_READ_MARKERS = ("read", "get", "list", "search", "find", "inspect", "availability", "query")
_WRITE_MARKERS = ("create", "update", "delete", "send", "draft", "archive", "label", "invite", "add", "remove")
_DESTRUCTIVE_MARKERS = ("delete", "remove")


def normalize_mcp_input_schema(input_schema: Any) -> Dict[str, Any]:
    if not isinstance(input_schema, dict):
        return {"type": "object", "properties": {}}
    normalized = dict(input_schema)
    normalized.setdefault("type", "object")
    properties = normalized.get("properties")
    if not isinstance(properties, dict):
        normalized["properties"] = {}
    required = normalized.get("required")
    if required is not None and not isinstance(required, list):
        normalized["required"] = []
    return normalized


def classify_mcp_tool(
    provider_id: str,
    tool_name: str,
) -> Tuple[RiskClass, ApprovalPolicy, ReadWriteCapability, bool, bool, bool]:
    provider = str(provider_id or "").lower()
    name = str(tool_name or "").lower()
    has_read = any(marker in name for marker in _READ_MARKERS)
    has_write = any(marker in name for marker in _WRITE_MARKERS)
    destructive = any(marker in name for marker in _DESTRUCTIVE_MARKERS)

    if provider.startswith("search_"):
        return (
            RiskClass.LOW,
            ApprovalPolicy.NO_APPROVAL_NEEDED,
            ReadWriteCapability.READ_ONLY,
            True,
            False,
            False,
        )

    if provider == "google_calendar":
        if has_write:
            return (
                RiskClass.HIGH,
                ApprovalPolicy.APPROVAL_REQUIRED,
                ReadWriteCapability.WRITE_CAPABLE,
                True,
                destructive,
                True,
            )
        return (
            RiskClass.LOW,
            ApprovalPolicy.NO_APPROVAL_NEEDED,
            ReadWriteCapability.READ_ONLY,
            False,
            False,
            True,
        )

    if provider == "gmail":
        if "draft" in name:
            return (
                RiskClass.MEDIUM,
                ApprovalPolicy.CONFIRMATION_RECOMMENDED,
                ReadWriteCapability.WRITE_CAPABLE,
                True,
                False,
                True,
            )
        if has_write:
            return (
                RiskClass.HIGH,
                ApprovalPolicy.APPROVAL_REQUIRED,
                ReadWriteCapability.WRITE_CAPABLE,
                True,
                destructive,
                True,
            )
        return (
            RiskClass.LOW,
            ApprovalPolicy.NO_APPROVAL_NEEDED,
            ReadWriteCapability.READ_ONLY,
            False,
            False,
            True,
        )

    if provider in {"whatsapp", "telegram"}:
        if "send" in name or "message" in name and has_write:
            return (
                RiskClass.HIGH,
                ApprovalPolicy.APPROVAL_REQUIRED,
                ReadWriteCapability.WRITE_CAPABLE,
                True,
                False,
                True,
            )
        return (
            RiskClass.LOW,
            ApprovalPolicy.NO_APPROVAL_NEEDED,
            ReadWriteCapability.READ_ONLY,
            False,
            False,
            True,
        )

    capability = ReadWriteCapability.READ_WRITE if has_read and has_write else (
        ReadWriteCapability.WRITE_CAPABLE if has_write else ReadWriteCapability.READ_ONLY if has_read else ReadWriteCapability.UNKNOWN
    )
    return (
        RiskClass.MEDIUM,
        ApprovalPolicy.CONFIRMATION_RECOMMENDED,
        capability,
        has_write,
        destructive,
        False,
    )


def normalize_mcp_tool_metadata(provider: MCPProviderConfig, raw_tool: Dict[str, Any]) -> ToolMetadata:
    raw_name = str(raw_tool.get("name") or "").strip()
    if not raw_name:
        raise ValueError("MCP tool metadata requires a non-empty name.")
    normalized_name = normalize_tool_id_part(raw_name)
    risk, approval, capability, external_side_effect, destructive, scheduled = classify_mcp_tool(
        provider.provider_id,
        raw_name,
    )
    is_available = provider.discovery_status == MCPDiscoveryStatus.DISCOVERED
    return ToolMetadata(
        tool_id=f"mcp.{provider.provider_id}.{normalized_name}",
        legacy_name=f"{provider.provider_id}_{normalized_name}",
        display_name=str(raw_tool.get("description") or raw_name).strip()[:120],
        provider=provider.provider_id,
        category=f"{provider.provider_id}_mcp",
        implementation_type=ImplementationType.MCP,
        enabled=bool(provider.enabled and is_available),
        availability_status=AvailabilityStatus.AVAILABLE if is_available else AvailabilityStatus.UNAVAILABLE,
        risk_class=risk,
        approval_policy=approval,
        read_write_capability=capability,
        external_side_effect=external_side_effect,
        destructive=destructive,
        scheduled_capable=scheduled,
        provider_managed=True,
        input_schema=normalize_mcp_input_schema(raw_tool.get("inputSchema")),
        output_schema_hint="mcp content",
        observability_metadata={
            "migration_phase": "T6",
            "provider_display_name": provider.display_name,
            "provider_managed": True,
            "raw_tool_name": raw_name,
            "transport_type": provider.transport_type.value,
            "discovery_status": provider.discovery_status.value,
        },
    )
