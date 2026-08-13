import json

from fastapi.testclient import TestClient

from src.db import init_db
from src.external_providers.telegram_bot_api import read_messages
from src.external_providers.whatsapp_api import ingest_webhook, read_messages as read_whatsapp, verify_webhook_token
from src.api.server import app


def test_whatsapp_webhook_ingest_and_read(tmp_path, monkeypatch):
    db_file = tmp_path / "wa.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    monkeypatch.setenv("WHATSAPP_API_TOKEN", "token-value")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "12345")

    stored = ingest_webhook({
        "object": "whatsapp_business_account",
        "entry": [{
            "changes": [{
                "value": {
                    "metadata": {"phone_number_id": "12345", "display_phone_number": "1555000"},
                    "messages": [{
                        "from": "15551234567",
                        "id": "wamid.abc",
                        "type": "text",
                        "text": {"body": "Namaste"},
                    }],
                }
            }]
        }],
    })
    assert stored == 1
    result = read_whatsapp(limit=5)
    assert result.ok
    assert "Namaste" in result.content
    assert "15551234567" in result.content


def test_whatsapp_webhook_verify_and_receive(tmp_path, monkeypatch):
    db_file = tmp_path / "wa_api.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "verify-me")
    client = TestClient(app)

    denied = client.get("/api/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.challenge": "42", "hub.verify_token": "nope"})
    assert denied.status_code == 403

    ok = client.get("/api/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.challenge": "42", "hub.verify_token": "verify-me"})
    assert ok.status_code == 200
    assert ok.text == "42"

    posted = client.post("/api/webhooks/whatsapp", json={
        "entry": [{"changes": [{"value": {"messages": [{"from": "1", "id": "wamid.1", "text": {"body": "hi"}}]}}]}]
    })
    assert posted.status_code == 200
    assert posted.json()["stored"] == 1
    assert verify_webhook_token("verify-me") is True


def test_telegram_read_ingests_get_updates(tmp_path, monkeypatch):
    db_file = tmp_path / "tg.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")

    from src.external_providers.common import ExternalProviderInvocationStatus, ExternalProviderResult

    payload = {
        "ok": True,
        "result": [{
            "update_id": 88,
            "message": {"chat": {"id": 99}, "text": "Hello bot"},
        }],
    }

    def fake_get_json(url, headers=None, timeout=20):
        return ExternalProviderResult(
            status=ExternalProviderInvocationStatus.SUCCEEDED,
            provider_id="telegram_bot_api",
            content=json.dumps(payload),
        )

    monkeypatch.setattr("src.external_providers.telegram_bot_api.get_json", fake_get_json)
    result = read_messages(limit=5)
    assert result.ok
    assert "Hello bot" in result.content
    assert "99" in result.content
