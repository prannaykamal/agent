from typing import List

from src.tools.registry_types import (
    ApprovalPolicy,
    AvailabilityStatus,
    ImplementationType,
    ReadWriteCapability,
    RiskClass,
    ToolMetadata,
)


REMOVED_BROWSER_SANDBOX_LEGACY_NAMES = ("safe_browse_url", "capture_screenshot")
REMOVED_CODE_SANDBOX_LEGACY_NAMES = (
    "run_code",
    "github_clone",
    "github_commit_and_push",
    "github_merge",
)
REMOVED_TOOL_LEGACY_NAMES = frozenset(
    REMOVED_BROWSER_SANDBOX_LEGACY_NAMES + REMOVED_CODE_SANDBOX_LEGACY_NAMES
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
            "migration_phase": "T1",
            "active_legacy_tool_may_still_exist": True,
            "target_state": "remove_completely",
        },
        replacement_tool_id=replacement_tool_id or None,
        removal_reason=removal_reason,
    )


REMOVED_TOOL_METADATA: List[ToolMetadata] = [
    _removed_metadata(
        tool_id="removed.browser.safe_browse_url",
        legacy_name="safe_browse_url",
        display_name="Browser Sandbox Browse URL",
        category="browser_sandbox",
        removal_reason="Browser sandbox is removed in the target tools architecture.",
        replacement_tool_id="mcp.search.provider_managed",
    ),
    _removed_metadata(
        tool_id="removed.browser.capture_screenshot",
        legacy_name="capture_screenshot",
        display_name="Browser Sandbox Capture Screenshot",
        category="browser_sandbox",
        removal_reason="Browser sandbox is removed in the target tools architecture.",
    ),
    _removed_metadata(
        tool_id="removed.code.run_code",
        legacy_name="run_code",
        display_name="Code Sandbox Run Code",
        category="code_sandbox",
        removal_reason="Code sandbox is removed in the target tools architecture.",
    ),
    _removed_metadata(
        tool_id="removed.code.github_clone",
        legacy_name="github_clone",
        display_name="Code Sandbox GitHub Clone",
        category="code_sandbox",
        removal_reason="GitHub/code sandbox tools are removed with the code sandbox.",
    ),
    _removed_metadata(
        tool_id="removed.code.github_commit_and_push",
        legacy_name="github_commit_and_push",
        display_name="Code Sandbox GitHub Commit And Push",
        category="code_sandbox",
        removal_reason="GitHub/code sandbox tools are removed with the code sandbox.",
    ),
    _removed_metadata(
        tool_id="removed.code.github_merge",
        legacy_name="github_merge",
        display_name="Code Sandbox GitHub Merge",
        category="code_sandbox",
        removal_reason="GitHub/code sandbox tools are removed with the code sandbox.",
    ),
]


def get_removed_tool_metadata() -> List[ToolMetadata]:
    """Returns metadata for tools targeted for removal by the tools migration."""
    return list(REMOVED_TOOL_METADATA)


def is_removed_tool_name(tool_name: str) -> bool:
    """Returns whether a legacy tool name is blocked by the T2 removed-tool policy."""
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

