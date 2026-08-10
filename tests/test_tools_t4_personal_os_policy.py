from src.hitl.classifier import classify_tool_risk
from src.personal_os.policy import classify_personal_os_action
from src.tools.registry_types import ApprovalPolicy, RiskClass, ReadWriteCapability


def test_t4_read_only_actions_need_no_approval():
    for name in ["list_tasks", "get_agent_status", "heartbeat", "restore_checkpoint"]:
        decision = classify_personal_os_action(name)
        assert decision.allowed is True
        assert decision.risk_class == RiskClass.LOW
        assert decision.approval_policy == ApprovalPolicy.NO_APPROVAL_NEEDED
        assert decision.read_write_capability == ReadWriteCapability.READ_ONLY


def test_t4_local_writes_are_policy_known():
    for name in ["create_task", "update_task", "publish_event", "checkpoint", "lock_resource"]:
        decision = classify_personal_os_action(name)
        assert decision.allowed is True
        assert decision.risk_class == RiskClass.MEDIUM
        assert decision.approval_policy == ApprovalPolicy.CONFIRMATION_RECOMMENDED
        assert decision.read_write_capability == ReadWriteCapability.WRITE_CAPABLE


def test_t4_lifecycle_destructive_and_scheduler_boundary_require_approval():
    for name in ["spawn_agent", "terminate_agent", "pause_agent", "resume_agent", "cancel_task", "schedule_job", "cancel_job"]:
        decision = classify_personal_os_action(name)
        assert decision.allowed is True
        assert decision.risk_class == RiskClass.HIGH
        assert decision.approval_policy == ApprovalPolicy.APPROVAL_REQUIRED


def test_t4_synthetic_tools_are_blocked_in_personal_and_hitl_policy():
    for name in ["sleep", "wake", "subscribe_event", "acquire_context", "release_context"]:
        decision = classify_personal_os_action(name)
        assert decision.allowed is False
        assert decision.risk_class == RiskClass.BLOCKED
        assert decision.approval_policy == ApprovalPolicy.BLOCKED
        assert classify_tool_risk(name)[0] == "Blocked"
