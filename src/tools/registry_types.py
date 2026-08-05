from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class ImplementationType(str, Enum):
    LOCAL = "local"
    MCP = "mcp"
    REMOVED = "removed"


class AvailabilityStatus(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    REMOVED = "removed"
    UNKNOWN = "unknown"


class RiskClass(str, Enum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    BLOCKED = "Blocked"


class ApprovalPolicy(str, Enum):
    NO_APPROVAL_NEEDED = "no_approval_needed"
    CONFIRMATION_RECOMMENDED = "confirmation_recommended"
    APPROVAL_REQUIRED = "approval_required"
    BLOCKED = "blocked"
    PROVIDER_MANAGED_CONFIRMATION = "provider_managed_confirmation"


class ReadWriteCapability(str, Enum):
    READ_ONLY = "read_only"
    WRITE_CAPABLE = "write_capable"
    READ_WRITE = "read_write"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ToolMetadata:
    tool_id: str
    legacy_name: str
    display_name: str
    provider: str
    category: str
    implementation_type: ImplementationType
    enabled: bool
    availability_status: AvailabilityStatus
    risk_class: RiskClass
    approval_policy: ApprovalPolicy
    read_write_capability: ReadWriteCapability
    external_side_effect: bool = False
    destructive: bool = False
    scheduled_capable: bool = False
    provider_managed: bool = False
    input_schema: Optional[Dict[str, Any]] = None
    output_schema_hint: Optional[str] = None
    observability_metadata: Dict[str, Any] = field(default_factory=dict)
    replacement_tool_id: Optional[str] = None
    removal_reason: Optional[str] = None

    def __post_init__(self) -> None:
        required = {
            "tool_id": self.tool_id,
            "legacy_name": self.legacy_name,
            "display_name": self.display_name,
            "provider": self.provider,
            "category": self.category,
        }
        missing = [name for name, value in required.items() if not str(value or "").strip()]
        if missing:
            raise ValueError(f"Missing required tool metadata field(s): {', '.join(missing)}")

        object.__setattr__(self, "implementation_type", ImplementationType(self.implementation_type))
        object.__setattr__(self, "availability_status", AvailabilityStatus(self.availability_status))
        object.__setattr__(self, "risk_class", RiskClass(self.risk_class))
        object.__setattr__(self, "approval_policy", ApprovalPolicy(self.approval_policy))
        object.__setattr__(self, "read_write_capability", ReadWriteCapability(self.read_write_capability))

        if self.implementation_type == ImplementationType.REMOVED:
            if self.enabled:
                raise ValueError("Removed tool metadata entries must not be enabled.")
            if not self.removal_reason:
                raise ValueError("Removed tool metadata entries require removal_reason.")

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        for key in (
            "implementation_type",
            "availability_status",
            "risk_class",
            "approval_policy",
            "read_write_capability",
        ):
            data[key] = data[key].value
        return data


def normalize_tool_id_part(value: str) -> str:
    normalized = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(value or "").strip())
    while "__" in normalized:
        normalized = normalized.replace("__", "_")
    return normalized.strip("_")


def approval_policy_for_risk(risk_class: str) -> ApprovalPolicy:
    risk = RiskClass(risk_class)
    if risk == RiskClass.HIGH:
        return ApprovalPolicy.APPROVAL_REQUIRED
    if risk == RiskClass.MEDIUM:
        return ApprovalPolicy.CONFIRMATION_RECOMMENDED
    if risk == RiskClass.BLOCKED:
        return ApprovalPolicy.BLOCKED
    return ApprovalPolicy.NO_APPROVAL_NEEDED


def infer_read_write_capability(tool_name: str) -> ReadWriteCapability:
    name = str(tool_name or "").lower()
    write_markers = (
        "create",
        "update",
        "delete",
        "cancel",
        "send",
        "draft",
        "propose",
        "schedule",
        "lock",
        "unlock",
        "publish",
        "acquire",
        "release",
        "checkpoint",
        "restore",
        "spawn",
        "terminate",
        "pause",
        "resume",
        "run",
        "commit",
        "merge",
        "clone",
        "screenshot",
    )
    read_markers = ("get", "list", "read", "search", "inspect", "heartbeat", "status")

    has_write = any(marker in name for marker in write_markers)
    has_read = any(marker in name for marker in read_markers)
    if has_read and has_write:
        return ReadWriteCapability.READ_WRITE
    if has_write:
        return ReadWriteCapability.WRITE_CAPABLE
    if has_read:
        return ReadWriteCapability.READ_ONLY
    return ReadWriteCapability.UNKNOWN


def schema_from_langchain_tool(tool: Any) -> Optional[Dict[str, Any]]:
    args_schema = getattr(tool, "args_schema", None)
    if args_schema is None:
        return None
    for method_name in ("model_json_schema", "schema"):
        method = getattr(args_schema, method_name, None)
        if callable(method):
            try:
                return method()
            except Exception:
                return None
    return None

