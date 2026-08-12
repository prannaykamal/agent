import pytest
from fastapi.testclient import TestClient

from src.api.server import app
from src.mcp_gateway.calendar import calendar_inspect_availability, calendar_create_event
from src.mcp_gateway.communication import whatsapp_read, whatsapp_send, telegram_read, telegram_send

client = TestClient(app)

def test_calendar_mcp_unavailable_truthfulness():
    """Calendar wrappers do not fall back to local storage when MCP is unavailable."""
    res_inspect = calendar_inspect_availability.invoke({"start_date": "2026-08-01", "end_date": "2026-08-02"})
    assert "Unavailable" in res_inspect

    res_create = calendar_create_event.invoke({"title": "Sync Test", "start_time": "2026-08-01 10:00", "end_time": "2026-08-01 11:00"})
    assert "Unavailable" in res_create

def test_whatsapp_telegram_direct_api_unavailable_truthfulness():
    """WhatsApp/Telegram wrappers do not fall back to local storage when MCP is unavailable."""
    assert "Unavailable" in whatsapp_read.invoke({"limit": 5})
    assert "Unavailable" in whatsapp_send.invoke({"recipient": "+1234567890", "message": "Test WA"})
    assert "Unavailable" in telegram_read.invoke({"limit": 5})
    assert "Unavailable" in telegram_send.invoke({"chat_id": "12345", "text": "Test TG"})

def test_api_integrations_status():
    """P1 Item 8: Verifies GET /api/integrations/status endpoint returns provider capabilities and truthfulness tags."""
    response = client.get("/api/integrations/status")
    assert response.status_code == 200
    data = response.json()
    assert "integrations" in data
    integrations = data["integrations"]

    assert "calendar" in integrations
    assert integrations["calendar"]["truthfulness"] in ("PROVIDER_MANAGED_MCP", "UNAVAILABLE")

    assert "whatsapp" in integrations
    assert integrations["whatsapp"]["truthfulness"] in ("DIRECT_API", "UNAVAILABLE")

    assert "telegram" in integrations
    assert integrations["telegram"]["truthfulness"] in ("DIRECT_API", "UNAVAILABLE")

    assert "search" in integrations
    assert integrations["search"]["truthfulness"] in ("PROVIDER_MANAGED_MCP", "UNAVAILABLE")
