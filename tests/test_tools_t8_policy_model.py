from src.tools.errors import ToolErrorCode
from src.tools.policy import ToolCallerSource, ToolPolicyDecisionType, evaluate_tool_policy
from src.tools.registry import get_all_tool_metadata_for_policy
from src.tools.registry_types import (
    ApprovalPolicy,
    AvailabilityStatus,
    ImplementationType,
    ReadWriteCapability,
    RiskClass,
    ToolMetadata,
)


def _metadata(name: str, *, approval=ApprovalPolicy.NO_APPROVAL_NEEDED, risk=RiskClass.LOW, provider="personal_os"):
    return ToolMetadata(
        tool_id=f"test.{name}",
        legacy_name=name,
        display_name=name,
        provider=provider,
        category="test",
        implementation_type=ImplementationType.MCP if provider != "personal_os" else ImplementationType.LOCAL,
        enabled=True,
        availability_status=AvailabilityStatus.AVAILABLE,
        risk_class=risk,
        approval_policy=approval,
        read_write_capability=ReadWriteCapability.WRITE_CAPABLE if risk == RiskClass.HIGH else ReadWriteCapability.READ_ONLY,
        external_side_effect=provider != "personal_os",
        destructive=False,
        provider_managed=provider != "personal_os",
    )


def test_t8_policy_decision_types_and_error_codes_exist():
    assert ToolPolicyDecisionType.NO_APPROVAL_NEEDED.value == "no_approval_needed"
    assert ToolPolicyDecisionType.CONFIRMATION_RECOMMENDED.value == "confirmation_recommended"
    assert ToolPolicyDecisionType.APPROVAL_REQUIRED.value == "approval_required"
    assert ToolPolicyDecisionType.BLOCKED.value == "blocked"
    assert ToolPolicyDecisionType.UNAVAILABLE.value == "unavailable"
    assert ToolErrorCode.REMOVED_TOOL.value == "REMOVED_TOOL"
    assert ToolErrorCode.POLICY_DENIED.value == "POLICY_DENIED"


def test_t8_every_policy_metadata_entry_has_required_policy_fields():
    metadata = get_all_tool_metadata_for_policy()
    assert metadata
    for item in metadata:
        assert item.tool_id
        assert item.provider
        assert item.category
        assert item.risk_class.value in {"Low", "Medium", "High", "Blocked"}
        assert item.approval_policy.value
        assert item.read_write_capability.value


def test_t8_policy_allows_approved_high_risk_context():
    decision = evaluate_tool_policy(
        "calendar_create_event",
        {"title": "demo"},
        source=ToolCallerSource.APPROVAL_RESUME,
        approval_context={"approved": True},
        metadata=_metadata("calendar_create_event", approval=ApprovalPolicy.APPROVAL_REQUIRED, risk=RiskClass.HIGH, provider="google_calendar"),
    )
    assert decision.decision == ToolPolicyDecisionType.NO_APPROVAL_NEEDED
    assert decision.risk_class == RiskClass.HIGH