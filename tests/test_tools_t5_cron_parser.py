from datetime import datetime, timezone

import pytest

from src.personal_os.cron_parser import CronParseError, next_cron_run_at, parse_cron_expression, parse_run_at


def test_t5_parse_valid_cron_expression():
    parsed = parse_cron_expression("*/15 9-17 * * 1-5")
    assert 0 in parsed.minutes
    assert 15 in parsed.minutes
    assert 9 in parsed.hours
    assert 17 in parsed.hours


def test_t5_invalid_cron_expression_rejected():
    with pytest.raises(CronParseError):
        parse_cron_expression("bad cron")
    with pytest.raises(CronParseError):
        parse_cron_expression("60 * * * *")


def test_t5_next_run_utc_is_deterministic():
    nxt = next_cron_run_at("0 9 * * *", "UTC", after="2026-08-10T08:58:00Z")
    assert nxt == "2026-08-10T09:00:00Z"


def test_t5_next_run_non_utc_timezone_is_normalized_to_utc():
    nxt = next_cron_run_at("0 9 * * *", "Asia/Calcutta", after="2026-08-10T00:00:00Z")
    assert nxt == "2026-08-10T03:30:00Z"


def test_t5_parse_run_at_uses_timezone_for_naive_input():
    assert parse_run_at("2026-08-10 09:00", "Asia/Calcutta") == "2026-08-10T03:30:00Z"
