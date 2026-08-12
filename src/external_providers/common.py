from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Iterable, Mapping, Optional

_SECRET_MARKERS = ("token", "secret", "password", "credential", "authorization", "api_key")
_PLACEHOLDER_MARKERS = ("", "your_", "placeholder", "changeme", "replace_me")
_SECRET_ENV_VARS = (
    "WHATSAPP_API_TOKEN",
    "TELEGRAM_BOT_TOKEN",
)


class ExternalProviderAvailability(str, Enum):
    CONFIGURED = "configured"
    MISSING_CONFIG = "missing_config"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class ExternalProviderInvocationStatus(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    INVOCATION_FAILED = "INVOCATION_FAILED"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True)
class ExternalProviderStatus:
    provider_id: str
    display_name: str
    availability_status: ExternalProviderAvailability
    configured: bool
    credential_status: str
    required_env_vars: tuple[str, ...]
    configured_env_vars: tuple[str, ...] = ()
    missing_env_vars: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    last_error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "display_name": self.display_name,
            "implementation_type": "external_api",
            "provider_managed": False,
            "availability_status": self.availability_status.value,
            "configured": self.configured,
            "credential_status": self.credential_status,
            "required_env_vars": list(self.required_env_vars),
            "configured_env_vars": list(self.configured_env_vars),
            "missing_env_vars": list(self.missing_env_vars),
            "capabilities": list(self.capabilities),
            "last_error": redact_text(self.last_error),
        }


@dataclass(frozen=True)
class ExternalProviderResult:
    status: ExternalProviderInvocationStatus
    provider_id: str
    content: str = ""
    error: str = ""
    audit_metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == ExternalProviderInvocationStatus.SUCCEEDED

    def to_text(self, label: str) -> str:
        if self.ok:
            return self.content or f"{label} action completed."
        detail = redact_text(self.error or self.content or "Provider is unavailable.") or "Provider is unavailable."
        return f"{label} Unavailable: {detail}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "provider_id": self.provider_id,
            "content": redact_text(self.content),
            "error": redact_text(self.error),
            "audit_metadata": redact_payload(self.audit_metadata),
        }


def _env_value(name: str) -> str:
    return str(os.getenv(name, "") or "").strip()


def _is_configured_value(value: str) -> bool:
    lowered = str(value or "").strip().lower()
    return bool(lowered) and not any(lowered.startswith(marker) for marker in _PLACEHOLDER_MARKERS if marker)


def configured_env_vars(names: Iterable[str]) -> tuple[str, ...]:
    return tuple(name for name in names if _is_configured_value(_env_value(name)))


def missing_env_vars(names: Iterable[str]) -> tuple[str, ...]:
    return tuple(name for name in names if not _is_configured_value(_env_value(name)))


def _configured_secret_values() -> tuple[str, ...]:
    values = []
    for name in _SECRET_ENV_VARS:
        value = _env_value(name)
        if _is_configured_value(value) and len(value) >= 4:
            values.append(value)
    return tuple(values)


def redact_text(value: Optional[str], *, limit: int = 240) -> Optional[str]:
    if value is None:
        return None
    text = str(value)
    for secret in _configured_secret_values():
        text = text.replace(secret, "[REDACTED]")
    lowered = text.lower()
    if any(marker in lowered for marker in _SECRET_MARKERS):
        return "[REDACTED]"
    return text[:limit] + ("..." if len(text) > limit else "")


def redact_payload(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: Dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if any(marker in key_text.lower() for marker in _SECRET_MARKERS):
                redacted[key_text] = "[REDACTED]"
            else:
                redacted[key_text] = redact_payload(item)
        return redacted
    if isinstance(value, list):
        return [redact_payload(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def build_status(
    *,
    provider_id: str,
    display_name: str,
    required_env_vars: tuple[str, ...],
    capabilities: tuple[str, ...],
) -> ExternalProviderStatus:
    configured = configured_env_vars(required_env_vars)
    missing = missing_env_vars(required_env_vars)
    is_ready = not missing
    return ExternalProviderStatus(
        provider_id=provider_id,
        display_name=display_name,
        availability_status=ExternalProviderAvailability.CONFIGURED if is_ready else ExternalProviderAvailability.MISSING_CONFIG,
        configured=is_ready,
        credential_status="configured" if is_ready else "missing",
        required_env_vars=required_env_vars,
        configured_env_vars=configured,
        missing_env_vars=missing,
        capabilities=capabilities,
    )


def unavailable_result(provider_id: str, status: ExternalProviderStatus) -> ExternalProviderResult:
    missing = ", ".join(status.missing_env_vars) if status.missing_env_vars else "required provider configuration"
    return ExternalProviderResult(
        status=ExternalProviderInvocationStatus.PROVIDER_UNAVAILABLE,
        provider_id=provider_id,
        error=f"Missing configuration: {missing}",
        audit_metadata={"missing_env_vars": list(status.missing_env_vars)},
    )


def validation_error(provider_id: str, message: str) -> ExternalProviderResult:
    return ExternalProviderResult(
        status=ExternalProviderInvocationStatus.VALIDATION_ERROR,
        provider_id=provider_id,
        error=message,
    )


def post_json(url: str, payload: Mapping[str, Any], *, headers: Mapping[str, str], timeout: int = 20) -> ExternalProviderResult:
    provider_id = str(headers.get("X-ASTRA-Provider-ID") or "external_api")
    clean_headers = {key: value for key, value in headers.items() if key != "X-ASTRA-Provider-ID"}
    request = urllib.request.Request(
        url,
        data=json.dumps(dict(payload)).encode("utf-8"),
        headers={**clean_headers, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return ExternalProviderResult(
                status=ExternalProviderInvocationStatus.SUCCEEDED,
                provider_id=provider_id,
                content="Provider API call succeeded.",
                audit_metadata={
                    "status_code": getattr(response, "status", None),
                    "response_preview": redact_text(body[:160]),
                },
            )
    except urllib.error.HTTPError as exc:
        detail = redact_text(exc.read().decode("utf-8", errors="replace")[:240]) or "Provider HTTP error"
        return ExternalProviderResult(
            status=ExternalProviderInvocationStatus.INVOCATION_FAILED,
            provider_id=provider_id,
            error=f"HTTP {exc.code}: {detail}",
        )
    except Exception as exc:
        return ExternalProviderResult(
            status=ExternalProviderInvocationStatus.INVOCATION_FAILED,
            provider_id=provider_id,
            error=redact_text(str(exc)) or "Provider invocation failed.",
        )
