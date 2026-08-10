import pytest
from src.config import validate_integration_environment


def test_p5_1_environment_validation_helper_reports_mcp_provider_readiness():
    env_status = validate_integration_environment()
    assert isinstance(env_status, dict)
    assert "smtp" in env_status
    assert "imap" in env_status
    assert "tavily" in env_status
    assert "telegram" in env_status
    assert "whatsapp" in env_status
    assert "google_calendar" in env_status


@pytest.mark.skip(reason="Manual provider-managed MCP validation is required outside automated tests.")
def test_p5_real_provider_smoke_validation_placeholder():
    assert False
