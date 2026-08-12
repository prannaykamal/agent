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

PROVIDER_ID = "whatsapp_api"
DISPLAY_NAME = "WhatsApp API"
REQUIRED_ENV_VARS = ("WHATSAPP_API_TOKEN", "WHATSAPP_PHONE_NUMBER_ID")
CAPABILITIES = ("status", "send_message")


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
        content="WhatsApp API is configured. Message reads require webhook/provider-side history and are not fetched by this local boundary.",
        audit_metadata={"capability": "status", "limit": limit},
    )


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
    return post_json(
        url,
        payload,
        headers={"Authorization": f"Bearer {token}", "X-ASTRA-Provider-ID": PROVIDER_ID},
    )
