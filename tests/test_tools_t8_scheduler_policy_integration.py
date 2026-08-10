from src.personal_os.scheduler_policy import decide_scheduler_execution


def test_t8_scheduler_read_only_action_can_execute_directly():
    decision = decide_scheduler_execution("heartbeat", {})
    assert decision.can_execute_directly is True
    assert decision.requires_approval is False


def test_t8_scheduler_write_and_provider_actions_are_approval_gated():
    local = decide_scheduler_execution("create_task", {"title": "x"})
    provider = decide_scheduler_execution("email_send", {"recipient": "a@example.com"})
    assert local.requires_approval is True
    assert provider.requires_approval is True
    assert provider.provider_action_deferred is True