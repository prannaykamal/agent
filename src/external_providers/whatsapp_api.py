from __future__ import annotations

import os
import uuid
from typing import Any, Dict, List, Mapping

from src.db import get_connection
from src.external_providers.common import (
    ExternalProviderInvocationStatus,
    ExternalProviderResult,
    build_status,
    post_json,
    unavailable_result,
    validation_error,
)

PROVIDER_ID = "whatsapp_api"
DISPLAY_NAME = "WhatsApp API"
REQUIRED_ENV_VARS = ("WHATSAPP_API_TOKEN", "WHATSAPP_PHONE_NUMBER_ID")
CAPABILITIES = ("status", "read_messages", "send_message")


def get_status() -> Dict[str, Any]:
    return build_status(
        provider_id=PROVIDER_ID,
        display_name=DISPLAY_NAME,
        required_env_vars=REQUIRED_ENV_VARS,
        capabilities=CAPABILITIES,
    ).to_dict()


def _store_message(sender: str, recipient: str, message: str, status: str, message_id: str = "") -> None:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT OR IGNORE INTO whatsapp_messages (id, sender, recipient, message, status, created_at)
        VALUES (?, ?, ?, ?, ?, datetime('now'))
        """,
        (message_id or f"wa_{uuid.uuid4().hex[:12]}", str(sender), str(recipient), str(message), status),
    )
    conn.commit()
    conn.close()


def _list_stored(limit: int) -> List[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, sender, recipient, message, status, created_at
        FROM whatsapp_messages
        ORDER BY created_at DESC, rowid DESC
        LIMIT ?
        """,
        (max(1, min(int(limit or 5), 20)),),
    )
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


def ingest_webhook(payload: Mapping[str, Any] | None) -> int:
    """Persist inbound Cloud API webhook messages into the local WhatsApp inbox."""
    data = dict(payload or {})
    stored = 0
    for entry in data.get("entry") or []:
        if not isinstance(entry, dict):
            continue
        for change in entry.get("changes") or []:
            if not isinstance(change, dict):
                continue
            value = change.get("value") if isinstance(change.get("value"), dict) else {}
            metadata = value.get("metadata") if isinstance(value.get("metadata"), dict) else {}
            business_number = str(metadata.get("display_phone_number") or metadata.get("phone_number_id") or "business")
            for message in value.get("messages") or []:
                if not isinstance(message, dict):
                    continue
                sender = str(message.get("from") or "").strip()
                text_obj = message.get("text") if isinstance(message.get("text"), dict) else {}
                body = str(text_obj.get("body") or message.get("type") or "").strip()
                message_id = str(message.get("id") or "").strip()
                if not sender:
                    continue
                _store_message(sender, business_number, body or "(non-text WhatsApp message)", "RECEIVED", message_id)
                stored += 1
    return stored


def verify_webhook_token(provided: str) -> bool:
    expected = str(os.getenv("WHATSAPP_VERIFY_TOKEN") or "").strip()
    return bool(expected) and expected == str(provided or "").strip()


def read_messages(limit: int = 5) -> ExternalProviderResult:
    status = build_status(
        provider_id=PROVIDER_ID,
        display_name=DISPLAY_NAME,
        required_env_vars=REQUIRED_ENV_VARS,
        capabilities=CAPABILITIES,
    )
    if not status.configured:
        return unavailable_result(PROVIDER_ID, status)

    capped = max(1, min(int(limit or 5), 20))
    rows = _list_stored(capped)
    if not rows:
        return ExternalProviderResult(
            status=ExternalProviderInvocationStatus.SUCCEEDED,
            provider_id=PROVIDER_ID,
            content=(
                "No WhatsApp messages stored yet. Meta Cloud API delivers inbound messages by webhook; "
                "point the app callback to POST /api/webhooks/whatsapp."
            ),
            audit_metadata={"capability": "read_messages", "limit": capped},
        )
    lines = [
        f"- {row['created_at']} | {row['sender']} → {row['recipient']} | {row['status']} | {row['message']}"
        for row in rows
    ]
    return ExternalProviderResult(
        status=ExternalProviderInvocationStatus.SUCCEEDED,
        provider_id=PROVIDER_ID,
        content="WhatsApp messages:\n" + "\n".join(lines),
        audit_metadata={"capability": "read_messages", "count": len(rows), "limit": capped},
    )


def read_status(limit: int = 5) -> ExternalProviderResult:
    return read_messages(limit=limit)


def send_message(recipient: str, message: str) -> ExternalProviderResult:
    clean_recipient = str(recipient or "").strip()
    clean_message = str(message or "").strip()
    if not clean_recipient:
        return validation_error(PROVIDER_ID, "recipient is required")
    if not clean_message:
        return validation_error(PROVIDER_ID, "message is required")

    status = build_status(
        provider_id=PROVIDER_ID,
        display_name=DISPLAY_NAME,
        required_env_vars=REQUIRED_ENV_VARS,
        capabilities=CAPABILITIES,
    )
    if not status.configured:
        return unavailable_result(PROVIDER_ID, status)

    token = os.getenv("WHATSAPP_API_TOKEN", "")
    phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
    api_version = os.getenv("WHATSAPP_API_VERSION", "v20.0")
    base_url = os.getenv("WHATSAPP_API_BASE_URL", "https://graph.facebook.com")
    url = f"{base_url.rstrip('/')}/{api_version}/{phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": clean_recipient,
        "type": "text",
        "text": {"body": clean_message},
    }
    result = post_json(
        url,
        payload,
        headers={"Authorization": f"Bearer {token}", "X-ASTRA-Provider-ID": PROVIDER_ID},
    )
    if result.ok:
        _store_message(phone_number_id, clean_recipient, clean_message, "SENT")
    return result
