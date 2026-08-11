from src.personal_os.registry import get_all_personal_os_tools, get_personal_os_tool_metadata
from src.tools.policy import ToolPolicyDecisionType, evaluate_tool_policy
from src.tools.registry import get_bindable_tool_metadata, get_tool_metadata_by_legacy_name
from src.tools.registry_types import ImplementationType, AvailabilityStatus, ApprovalPolicy

SYNTHETIC = {"sleep", "wake", "subscribe_event", "acquire_context", "release_context"}


def test_t4_active_personal_os_tools_are_local_and_bounded():
    active_names = {tool.name for tool in get_all_personal_os_tools()}
    assert "create_task" in active_names
    assert "list_tasks" in active_names
    assert "heartbeat" in active_names
    assert "publish_event" in active_names
    assert "checkpoint" in active_names
    assert active_names.isdisjoint(SYNTHETIC)

    metadata = get_personal_os_tool_metadata()
    assert {item.legacy_name for item in metadata} == active_names
    for item in metadata:
        assert item.provider == "personal_os"
        assert item.implementation_type == ImplementationType.LOCAL
        assert item.availability_status == AvailabilityStatus.AVAILABLE
        assert item.enabled is True
        assert item.risk_class.value in {"Low", "Medium", "High"}
        assert item.approval_policy in {
            ApprovalPolicy.NO_APPROVAL_NEEDED,
            ApprovalPolicy.CONFIRMATION_RECOMMENDED,
            ApprovalPolicy.APPROVAL_REQUIRED,
        }
        assert item.external_side_effect is False
        assert item.provider_managed is False
        assert item.tool_id.startswith("local.personal_os.")


def test_t4_deprecated_synthetic_tools_have_no_local_metadata_and_are_blocked():
    all_metadata = get_personal_os_tool_metadata(include_deprecated=True)
    by_name = {item.legacy_name for item in all_metadata}
    bindable_names = {item.legacy_name for item in get_bindable_tool_metadata()}

    for name in SYNTHETIC:
        assert name not in by_name
        assert name not in bindable_names
        assert get_tool_metadata_by_legacy_name(name) is None
        assert evaluate_tool_policy(name, {}).decision == ToolPolicyDecisionType.BLOCKED


def test_t4_personal_os_registry_excludes_provider_and_sandbox_tools():
    active_names = {tool.name for tool in get_all_personal_os_tools()}
    forbidden = {
        "email_send", "email_read", "whatsapp_send", "telegram_send",
        "calendar_create_event", "search_web",
        "safe_browse_url", "capture_screenshot", "run_code", "github_merge",
    }
    assert active_names.isdisjoint(forbidden)
