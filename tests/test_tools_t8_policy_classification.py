from src.tools.policy import ToolCallerSource, ToolPolicyDecisionType, evaluate_tool_policy
from src.tools.registry_types import ApprovalPolicy, AvailabilityStatus, ImplementationType, ReadWriteCapability, RiskClass, ToolMetadata
from src.hitl.classifier import classify_tool_risk


def meta(name, provider, risk, approval, capability=ReadWriteCapability.READ_ONLY, external=False, destructive=False, implementation_type=ImplementationType.MCP, provider_managed=True):
    return ToolMetadata(
        tool_id=f"{implementation_type.value}.{provider}.{name}",
        legacy_name=name,
        display_name=name,
        provider=provider,
        category=f"{provider}_mcp" if implementation_type == ImplementationType.MCP else f"{provider}_direct",
        implementation_type=implementation_type,
        enabled=True,
        availability_status=AvailabilityStatus.AVAILABLE,
        risk_class=risk,
        approval_policy=approval,
        read_write_capability=capability,
        external_side_effect=external,
        destructive=destructive,
        provider_managed=provider_managed,
    )


def test_t8_search_read_only_needs_no_approval():
    decision = evaluate_tool_policy("search_web", {"query": "weather"}, metadata=meta("search_web", "search_tavily", RiskClass.LOW, ApprovalPolicy.NO_APPROVAL_NEEDED, external=True))
    assert decision.decision == ToolPolicyDecisionType.NO_APPROVAL_NEEDED


def test_t8_sensitive_search_is_confirmation_recommended():
    decision = evaluate_tool_policy("search_web", {"query": "find leaked api key"}, metadata=meta("search_web", "search_tavily", RiskClass.LOW, ApprovalPolicy.NO_APPROVAL_NEEDED, external=True))
    assert decision.decision == ToolPolicyDecisionType.CONFIRMATION_RECOMMENDED


def test_t8_calendar_gmail_whatsapp_telegram_writes_require_approval():
    cases = [
        ("calendar_create_event", "google_calendar", ImplementationType.MCP, True),
        ("gmail_send", "gmail", ImplementationType.MCP, True),
        ("whatsapp_send", "whatsapp_api", ImplementationType.EXTERNAL_API, False),
        ("telegram_send", "telegram_bot_api", ImplementationType.EXTERNAL_API, False),
    ]
    for name, provider, implementation_type, provider_managed in cases:
        decision = evaluate_tool_policy(
            name,
            {},
            metadata=meta(
                name,
                provider,
                RiskClass.HIGH,
                ApprovalPolicy.APPROVAL_REQUIRED,
                ReadWriteCapability.WRITE_CAPABLE,
                external=True,
                implementation_type=implementation_type,
                provider_managed=provider_managed,
            ),
        )
        assert decision.decision == ToolPolicyDecisionType.APPROVAL_REQUIRED


def test_t8_personal_os_read_direct_and_write_policy_known():
    assert evaluate_tool_policy("heartbeat", {}).decision == ToolPolicyDecisionType.NO_APPROVAL_NEEDED
    create_task = evaluate_tool_policy("create_task", {"title": "x"})
    assert create_task.decision == ToolPolicyDecisionType.CONFIRMATION_RECOMMENDED
    assert create_task.risk_class == RiskClass.MEDIUM


def test_t8_removed_demo_tools_and_real_high_risk_classification_delegate_to_policy():
    assert classify_tool_risk("run_code")[0] == "Blocked"
    assert classify_tool_risk("delete_database")[0] == "Blocked"
    assert classify_tool_risk("bank_transfer")[0] == "Blocked"
    assert classify_tool_risk("email_send")[0] == "High"


