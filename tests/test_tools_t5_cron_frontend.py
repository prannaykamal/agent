from pathlib import Path


def test_t5_scheduled_cockpit_uses_new_cron_endpoints():
    source = Path("frontend/src/components/ScheduledCockpit.jsx").read_text()
    assert "/api/tools/cron/schedules" in source
    assert "/api/tools/cron/runs" in source
    assert "schedule_type" in source
    assert "timezone" in source
    assert "missed_run_policy" in source


def test_t5_scheduled_cockpit_does_not_call_removed_or_provider_routes():
    source = Path("frontend/src/components/ScheduledCockpit.jsx").read_text()
    forbidden = ["/api/browser", "/api/github", "gmail", "whatsapp", "telegram", "google-calendar"]
    assert all(term not in source.lower() for term in forbidden)
