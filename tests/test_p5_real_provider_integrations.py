import os
import pytest
from src.config import validate_integration_environment
from src.mcp_gateway.communication import telegram_send, whatsapp_send, email_send, email_read
from src.mcp_gateway.calendar import calendar_create_event
from src.mcp_gateway.search_adapters import perform_web_search

def test_p5_1_environment_validation_helper():
    """P5 Item 7: Verifies validate_integration_environment helper returns dictionary of provider readiness flags."""
    env_status = validate_integration_environment()
    assert isinstance(env_status, dict)
    assert "smtp" in env_status
    assert "imap" in env_status
    assert "tavily" in env_status
    assert "telegram" in env_status
    assert "whatsapp" in env_status
    assert "google_calendar" in env_status

@pytest.mark.skipif(not os.getenv("TELEGRAM_BOT_TOKEN"), reason="TELEGRAM_BOT_TOKEN environment variable not configured")
def test_p5_2_telegram_bot_api_real_integration():
    """P5 Item 1 & 8: Real Telegram Bot API integration test gated by TELEGRAM_BOT_TOKEN."""
    chat_id = os.getenv("TELEGRAM_TEST_CHAT_ID", "12345678")
    res = telegram_send.invoke({"chat_id": chat_id, "text": "Integration test ping from Personal Assistant agent."})
    assert "[Telegram MCP" in res
    assert "SENT" in res

@pytest.mark.skipif(not (os.getenv("WHATSAPP_API_TOKEN") and os.getenv("WHATSAPP_PHONE_NUMBER_ID")), reason="WhatsApp Cloud API environment variables not configured")
def test_p5_3_whatsapp_cloud_api_real_integration():
    """P5 Item 2 & 8: Real WhatsApp Meta Graph API integration test gated by WHATSAPP_API_TOKEN."""
    to_phone = os.getenv("WHATSAPP_TEST_RECIPIENT", "+1234567890")
    res = whatsapp_send.invoke({"recipient": to_phone, "message": "WhatsApp integration test from Personal Assistant agent."})
    assert "[WhatsApp MCP" in res
    assert "SENT" in res

@pytest.mark.skipif(not os.getenv("GOOGLE_CALENDAR_TOKEN"), reason="GOOGLE_CALENDAR_TOKEN environment variable not configured")
def test_p5_4_google_calendar_real_api_sync():
    """P5 Item 3 & 8: Real Google Calendar v3 API sync test gated by GOOGLE_CALENDAR_TOKEN."""
    res = calendar_create_event.invoke({
        "title": "Google Calendar API Sync Test",
        "start_time": "2026-09-01T10:00:00Z",
        "end_time": "2026-09-01T11:00:00Z"
    })
    assert "[Calendar MCP" in res
    assert "CREATED" in res

@pytest.mark.skipif(not (os.getenv("SMTP_HOST") and os.getenv("SMTP_USER")), reason="SMTP environment variables not configured")
def test_p5_5_smtp_email_send_real_integration():
    """P5 Item 8: Real SMTP email transmission test gated by SMTP_HOST."""
    recipient = os.getenv("SMTP_TEST_RECIPIENT", "test@example.com")
    res = email_send.invoke({"to": recipient, "subject": "SMTP Integration Test", "body": "Testing live SMTP adapter."})
    assert "[Email MCP - SENT" in res

@pytest.mark.skipif(not os.getenv("TAVILY_API_KEY"), reason="TAVILY_API_KEY environment variable not configured")
def test_p5_6_tavily_search_api_real_integration():
    """P5 Item 4 & 8: Real Tavily REST API search test gated by TAVILY_API_KEY."""
    results = perform_web_search(query="Python 3.12 release notes", max_results=3)
    assert len(results) >= 1
    assert "url" in results[0]
    assert "title" in results[0]
