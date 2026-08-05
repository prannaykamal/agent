import pytest

from src.tools.registry_types import (
    ApprovalPolicy,
    AvailabilityStatus,
    ImplementationType,
    ReadWriteCapability,
    RiskClass,
    ToolMetadata,
    approval_policy_for_risk,
    infer_read_write_capability,
    normalize_tool_id_part,
)


def test_t1_registry_types_support_local_mcp_and_removed_implementation_types():
    assert ImplementationType.LOCAL.value == "local"
    assert ImplementationType.MCP.value == "mcp"
    assert ImplementationType.REMOVED.value == "removed"


def test_t1_tool_metadata_validates_required_fields_and_policy_fields():
    metadata = ToolMetadata(
        tool_id="local.personal_os.heartbeat",
        legacy_name="heartbeat",
        display_name="Heartbeat",
        provider="personal_os",
        category="health",
        implementation_type="local",
        enabled=True,
        availability_status="available",
        risk_class="Low",
        approval_policy="no_approval_needed",
        read_write_capability="read_only",
    )

    assert metadata.implementation_type == ImplementationType.LOCAL
    assert metadata.availability_status == AvailabilityStatus.AVAILABLE
    assert metadata.risk_class == RiskClass.LOW
    assert metadata.approval_policy == ApprovalPolicy.NO_APPROVAL_NEEDED
    assert metadata.read_write_capability == ReadWriteCapability.READ_ONLY
    assert metadata.to_dict()["implementation_type"] == "local"


def test_t1_tool_metadata_rejects_missing_required_fields():
    with pytest.raises(ValueError, match="legacy_name"):
        ToolMetadata(
            tool_id="local.personal_os.bad",
            legacy_name="",
            display_name="Bad",
            provider="personal_os",
            category="bad",
            implementation_type=ImplementationType.LOCAL,
            enabled=True,
            availability_status=AvailabilityStatus.AVAILABLE,
            risk_class=RiskClass.LOW,
            approval_policy=ApprovalPolicy.NO_APPROVAL_NEEDED,
            read_write_capability=ReadWriteCapability.UNKNOWN,
        )


def test_t1_removed_metadata_requires_removal_reason_and_is_disabled():
    with pytest.raises(ValueError, match="must not be enabled"):
        ToolMetadata(
            tool_id="removed.code.run_code",
            legacy_name="run_code",
            display_name="Run Code",
            provider="removed",
            category="code_sandbox",
            implementation_type=ImplementationType.REMOVED,
            enabled=True,
            availability_status=AvailabilityStatus.REMOVED,
            risk_class=RiskClass.BLOCKED,
            approval_policy=ApprovalPolicy.BLOCKED,
            read_write_capability=ReadWriteCapability.UNKNOWN,
            removal_reason="Target removed.",
        )

    with pytest.raises(ValueError, match="removal_reason"):
        ToolMetadata(
            tool_id="removed.code.run_code",
            legacy_name="run_code",
            display_name="Run Code",
            provider="removed",
            category="code_sandbox",
            implementation_type=ImplementationType.REMOVED,
            enabled=False,
            availability_status=AvailabilityStatus.REMOVED,
            risk_class=RiskClass.BLOCKED,
            approval_policy=ApprovalPolicy.BLOCKED,
            read_write_capability=ReadWriteCapability.UNKNOWN,
        )


def test_t1_removed_metadata_supports_replacement_tool_id():
    metadata = ToolMetadata(
        tool_id="removed.browser.safe_browse_url",
        legacy_name="safe_browse_url",
        display_name="Browser Browse",
        provider="removed",
        category="browser_sandbox",
        implementation_type=ImplementationType.REMOVED,
        enabled=False,
        availability_status=AvailabilityStatus.REMOVED,
        risk_class=RiskClass.BLOCKED,
        approval_policy=ApprovalPolicy.BLOCKED,
        read_write_capability=ReadWriteCapability.UNKNOWN,
        replacement_tool_id="mcp.search.provider_managed",
        removal_reason="Browser sandbox target removal.",
    )

    assert metadata.replacement_tool_id == "mcp.search.provider_managed"
    assert metadata.removal_reason


def test_t1_registry_type_helpers_are_deterministic():
    assert normalize_tool_id_part("GitHub Commit & Push") == "github_commit_push"
    assert approval_policy_for_risk("High") == ApprovalPolicy.APPROVAL_REQUIRED
    assert approval_policy_for_risk("Medium") == ApprovalPolicy.CONFIRMATION_RECOMMENDED
    assert infer_read_write_capability("search_web") == ReadWriteCapability.READ_ONLY
    assert infer_read_write_capability("calendar_update_event") == ReadWriteCapability.WRITE_CAPABLE
