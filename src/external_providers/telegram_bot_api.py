from __future__ import annotations

import os
from typing import Any, Dict

from src.external_providers.common import (
    ExternalProviderInvocationStatus,
    ExternalProviderResult,
    build_status,
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


def read_status(limit: int = 5) -> ExternalProviderResult:
    status = build_status(
        provider_id=PROVIDER_ID,
        display_name=DISPLAY_NAME,
        required_env_vars=REQUIRED_ENV_VARS,
        capabilities=CAPABILITIES,
    )
    if not status.configured:
        return unavailable_result(PROVIDER_ID, status)
    return ExternalProviderResult(
        status=ExternalProviderInvocationStatus.SUCCEEDED,
        provider_id=PROVIDER_ID,
        content="Telegram Bot API is configured. Reading updates is intentionally not performed by this status boundary.",
        audit_metadata={"capability": "status", "limit": limit},
    )


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

    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    base_url = os.getenv("TELEGRAM_API_BASE_URL", "https://api.telegram.org")
    url = f"{base_url.rstrip('/')}/bot{token}/sendMessage"
    payload = {"chat_id": clean_chat_id, "text": clean_text}
    return post_json(
        url,
        payload,
        headers={"X-ASTRA-Provider-ID": PROVIDER_ID},
    )
