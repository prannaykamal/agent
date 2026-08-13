from __future__ import annotations

import json
import os
import uuid
from typing import Any, Dict, List

from src.db import get_connection
from src.external_providers.common import (
    ExternalProviderInvocationStatus,
    ExternalProviderResult,
    build_status,
    get_json,
    post_json,
    unavailable_result,
    validation_error,
)

PROVIDER_ID = "telegram_bot_api"
DISPLAY_NAME = "Telegram Bot API"
REQUIRED_ENV_VARS = ("TELEGRAM_BOT_TOKEN",)
CAPABILITIES = ("status", "read_updates", "send_message")


def get_status() -> Dict[str, Any]:
    return build_status(
        provider_id=PROVIDER_ID,
        display_name=DISPLAY_NAME,
        required_env_vars=REQUIRED_ENV_VARS,
        capabilities=CAPABILITIES,
    ).to_dict()


def _api_root() -> str:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    base_url = os.getenv("TELEGRAM_API_BASE_URL", "https://api.telegram.org")
    return f"{base_url.rstrip('/')}/bot{token}"


def _store_message(chat_id: str, message: str, status: str, message_id: str = "") -> None:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT OR IGNORE INTO telegram_messages (id, chat_id, message, status, created_at)
        VALUES (?, ?, ?, ?, datetime('now'))
        """,
        (message_id or f"tg_{uuid.uuid4().hex[:12]}", str(chat_id), str(message), status),
    )
    conn.commit()
    conn.close()


def _list_stored(limit: int) -> List[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, chat_id, message, status, created_at
        FROM telegram_messages
        ORDER BY created_at DESC, rowid DESC
        LIMIT ?
        """,
        (max(1, min(int(limit or 5), 20)),),
    )
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


def _ingest_updates(payload: Any) -> int:
    if not isinstance(payload, dict):
        return 0
    results = payload.get("result")
    if not isinstance(results, list):
        return 0
    stored = 0
    max_update_id = 0
    for item in results:
        if not isinstance(item, dict):
            continue
        update_id = int(item.get("update_id") or 0)
        max_update_id = max(max_update_id, update_id)
        message = item.get("message") or item.get("edited_message") or {}
        if not isinstance(message, dict):
            continue
        chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
        chat_id = str(chat.get("id") or "").strip()
        text = str(message.get("text") or message.get("caption") or "").strip()
        if not chat_id:
            continue
        _store_message(chat_id, text or "(non-text Telegram update)", "RECEIVED", f"tg_upd_{update_id}")
        stored += 1
    if max_update_id:
        get_json(
            f"{_api_root()}/getUpdates?offset={max_update_id + 1}&limit=1",
            headers={"X-ASTRA-Provider-ID": PROVIDER_ID},
        )
    return stored


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
    updates = get_json(
        f"{_api_root()}/getUpdates?limit={capped}&timeout=0",
        headers={"X-ASTRA-Provider-ID": PROVIDER_ID},
    )
    if updates.ok:
        try:
            payload = json.loads(updates.content) if updates.content.startswith("{") else {}
        except json.JSONDecodeError:
            payload = {}
        if isinstance(payload, dict) and "result" in payload:
            _ingest_updates(payload)
        elif updates.audit_metadata.get("response_preview"):
            try:
                _ingest_updates(json.loads(str(updates.audit_metadata.get("response_preview") or "{}")))
            except json.JSONDecodeError:
                pass

    rows = _list_stored(capped)
    if not rows:
        return ExternalProviderResult(
            status=ExternalProviderInvocationStatus.SUCCEEDED,
            provider_id=PROVIDER_ID,
            content="No Telegram messages yet. Send a message to the bot, then call telegram_read again.",
            audit_metadata={"capability": "read_updates", "limit": capped},
        )
    lines = [
        f"- {row['created_at']} | chat {row['chat_id']} | {row['status']} | {row['message']}"
        for row in rows
    ]
    return ExternalProviderResult(
        status=ExternalProviderInvocationStatus.SUCCEEDED,
        provider_id=PROVIDER_ID,
        content="Telegram messages:\n" + "\n".join(lines),
        audit_metadata={"capability": "read_updates", "count": len(rows), "limit": capped},
    )


def read_status(limit: int = 5) -> ExternalProviderResult:
    return read_messages(limit=limit)


def send_message(chat_id: str, text: str) -> ExternalProviderResult:
    clean_chat_id = str(chat_id or "").strip()
    clean_text = str(text or "").strip()
    if not clean_chat_id:
        return validation_error(PROVIDER_ID, "chat_id is required")
    if not clean_text:
        return validation_error(PROVIDER_ID, "text is required")

    status = build_status(
        provider_id=PROVIDER_ID,
        display_name=DISPLAY_NAME,
        required_env_vars=REQUIRED_ENV_VARS,
        capabilities=CAPABILITIES,
    )
    if not status.configured:
        return unavailable_result(PROVIDER_ID, status)

    result = post_json(
        f"{_api_root()}/sendMessage",
        {"chat_id": clean_chat_id, "text": clean_text},
        headers={"X-ASTRA-Provider-ID": PROVIDER_ID},
    )
    if result.ok:
        _store_message(clean_chat_id, clean_text, "SENT")
    return result
