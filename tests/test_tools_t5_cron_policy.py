from src.personal_os.scheduler_policy import decide_scheduler_execution
from src.personal_os.scheduler_service import default_missed_policy_for_target


def test_t5_read_only_local_action_can_execute_directly():
    decision = decide_scheduler_execution("heartbeat", {})
    assert decision.can_execute_directly is True
    assert decision.requires_approval is False


def test_t5_local_write_action_is_approval_gated():
    decision = decide_scheduler_execution("create_task", {"title": "x"})
    assert decision.can_execute_directly is False
    assert decision.requires_approval is True


def test_t5_provider_action_deferred_and_approval_gated():
    decision = decide_scheduler_execution("email_send", {"recipient": "a@example.com"})
    assert decision.provider_action_deferred is True
    assert decision.requires_approval is True


def test_t5_default_missed_policy_read_vs_high_risk():
    assert default_missed_policy_for_target("heartbeat") == "run_once"
    assert default_missed_policy_for_target("email_send") == "skip"
