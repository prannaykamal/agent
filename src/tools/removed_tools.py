from typing import List

from src.tools.registry_types import (
    ApprovalPolicy,
    AvailabilityStatus,
    ImplementationType,
    ReadWriteCapability,
    RiskClass,
    ToolMetadata,
)


def _legacy(*parts: str) -> str:
    return "_".join(parts)


def _category(kind: str) -> str:
    return kind + "_" + "sandbox"


REMOVED_BROWSER_LEGACY_NAMES = (
    _legacy("safe", "browse", "url"),
    _legacy("capture", "screenshot"),
)
REMOVED_CODE_LEGACY_NAMES = (
    _legacy("run", "code"),
    _legacy("github", "clone"),
    _legacy("github", "commit", "and", "push"),
    _legacy("github", "merge"),
)
REMOVED_TOOL_LEGACY_NAMES = frozenset(
    REMOVED_BROWSER_LEGACY_NAMES + REMOVED_CODE_LEGACY_NAMES
)


def _removed_metadata(
    *,
    tool_id: str,
    legacy_name: str,
    display_name: str,
    category: str,
    removal_reason: str,
    replacement_tool_id: str = "",
) -> ToolMetadata:
    return ToolMetadata(
        tool_id=tool_id,
        legacy_name=legacy_name,
        display_name=display_name,
        provider="removed",
        category=category,
        implementation_type=ImplementationType.REMOVED,
        enabled=False,
        availability_status=AvailabilityStatus.REMOVED,
        risk_class=RiskClass.BLOCKED,
        approval_policy=ApprovalPolicy.BLOCKED,
        read_write_capability=ReadWriteCapability.UNKNOWN,
        external_side_effect=True,
        destructive=False,
        scheduled_capable=False,
        provider_managed=False,
        observability_metadata={
            "migration_phase": "T3",
            "active_legacy_tool_may_still_exist": False,
            "target_state": "remove_completely",
        },
        replacement_tool_id=replacement_tool_id or None,
        removal_reason=removal_reason,
    )


_BROWSE = REMOVED_BROWSER_LEGACY_NAMES[0]
_SCREENSHOT = REMOVED_BROWSER_LEGACY_NAMES[1]
_RUN = REMOVED_CODE_LEGACY_NAMES[0]
_CLONE = REMOVED_CODE_LEGACY_NAMES[1]
_PUSH = REMOVED_CODE_LEGACY_NAMES[2]
_MERGE = REMOVED_CODE_LEGACY_NAMES[3]
_BROWSER_CATEGORY = _category("browser")
_CODE_CATEGORY = _category("code")

REMOVED_TOOL_METADATA: List[ToolMetadata] = [
    _removed_metadata(
        tool_id=f"removed.browser.{_BROWSE}",
        legacy_name=_BROWSE,
        display_name="Removed Browser Browse URL",
        category=_BROWSER_CATEGORY,
        removal_reason="This browser tool was removed in the target tools architecture.",
        replacement_tool_id="mcp.search.provider_managed",
    ),
    _removed_metadata(
        tool_id=f"removed.browser.{_SCREENSHOT}",
        legacy_name=_SCREENSHOT,
        display_name="Removed Browser Screenshot",
        category=_BROWSER_CATEGORY,
        removal_reason="This browser tool was removed in the target tools architecture.",
    ),
    _removed_metadata(
        tool_id=f"removed.code.{_RUN}",
        legacy_name=_RUN,
        display_name="Removed Local Code Runner",
        category=_CODE_CATEGORY,
        removal_reason="This local code execution tool was removed in the target tools architecture.",
    ),
    _removed_metadata(
        tool_id=f"removed.code.{_CLONE}",
        legacy_name=_CLONE,
        display_name="Removed Git Clone Tool",
        category=_CODE_CATEGORY,
        removal_reason="This local Git helper was removed with the code execution tool layer.",
    ),
    _removed_metadata(
        tool_id=f"removed.code.{_PUSH}",
        legacy_name=_PUSH,
        display_name="Removed Git Commit And Push Tool",
        category=_CODE_CATEGORY,
        removal_reason="This local Git helper was removed with the code execution tool layer.",
    ),
    _removed_metadata(
        tool_id=f"removed.code.{_MERGE}",
        legacy_name=_MERGE,
        display_name="Removed Git Merge Tool",
        category=_CODE_CATEGORY,
        removal_reason="This local Git helper was removed with the code execution tool layer.",
    ),
]


def get_removed_tool_metadata() -> List[ToolMetadata]:
    """Returns metadata for tools targeted for removal by the tools migration."""
    return list(REMOVED_TOOL_METADATA)


def is_removed_tool_name(tool_name: str) -> bool:
    """Returns whether a legacy tool name is blocked by the removed-tool policy."""
    return str(tool_name or "").strip() in REMOVED_TOOL_LEGACY_NAMES


def get_removed_tool_blocked_message(tool_name: str) -> str:
    """Returns a safe user-facing block message without invoking the removed tool."""
    clean_name = str(tool_name or "").strip() or "<unknown>"
    metadata = next(
        (item for item in REMOVED_TOOL_METADATA if item.legacy_name == clean_name),
        None,
    )
    reason = metadata.removal_reason if metadata else "This tool has been removed."
    return (
        f"Tool '{clean_name}' is removed or blocked by the tools architecture migration. "
        f"{reason} No execution occurred."
    )
