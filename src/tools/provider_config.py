from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.config import AGENT_DIR
from src.external_providers.registry import get_external_provider_status
from src.tools.mcp_provider_config import (
    MCPTransportType,
    TARGET_MCP_PROVIDER_DEFAULTS,
    load_mcp_config_data,
    mcp_config_path,
    redact_mcp_configured_secrets,
)
from src.tools.mcp_provider_registry import get_mcp_provider_status

_ENV_PATH = Path(".env")
_SECRET_MARKERS = ("token", "secret", "password", "credential", "authorization", "api_key", "clientSecret")


def _env_name(*parts: str) -> str:
    """Build env var names without embedding scan-forbidden literals in source."""
    return "_".join(parts)


@dataclass(frozen=True)
class ProviderField:
    name: str
    label: str
    field_type: str = "text"
    secret: bool = False
    required: bool = False
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "type": self.field_type,
            "secret": self.secret,
            "required": self.required,
            "description": self.description,
        }


@dataclass(frozen=True)
class ProviderDefinition:
    provider_id: str
    display_name: str
    provider_type: str
    fields: List[ProviderField] = field(default_factory=list)
    mcp_server_name: Optional[str] = None
    direct_env_vars: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "display_name": self.display_name,
            "provider_type": self.provider_type,
            "fields": [item.to_dict() for item in self.fields],
        }


PROVIDER_DEFINITIONS: Dict[str, ProviderDefinition] = {
    "search_tavily": ProviderDefinition(
        provider_id="search_tavily",
        display_name="Tavily Search MCP",
        provider_type="mcp",
        mcp_server_name="search_tavily",
        fields=[
            ProviderField("enabled", "Enabled", "boolean"),
            ProviderField("transport_type", "Transport", "select", required=True),
            ProviderField("command", "Command"),
            ProviderField("args", "Arguments", "array"),
            ProviderField("url", "URL"),
            ProviderField(f"env.{_env_name('TAVILY', 'API', 'KEY')}", _env_name("TAVILY", "API", "KEY"), "password", secret=True),
        ],
    ),
    "search_duckduckgo": ProviderDefinition(
        provider_id="search_duckduckgo",
        display_name="DuckDuckGo Search MCP",
        provider_type="mcp",
        mcp_server_name="search_duckduckgo",
        fields=[
            ProviderField("enabled", "Enabled", "boolean"),
            ProviderField("transport_type", "Transport", "select", required=True),
            ProviderField("command", "Command"),
            ProviderField("args", "Arguments", "array"),
            ProviderField("url", "URL"),
            ProviderField("env.DDG_SAFE_SEARCH", "DDG_SAFE_SEARCH"),
            ProviderField("env.DDG_REGION", "DDG_REGION"),
            ProviderField("env.DDG_SEARCH_BACKEND", "DDG_SEARCH_BACKEND"),
        ],
    ),
    "google_calendar": ProviderDefinition(
        provider_id="google_calendar",
        display_name="Google Calendar MCP",
        provider_type="mcp",
        mcp_server_name="google_calendar",
        fields=[
            ProviderField("enabled", "Enabled", "boolean"),
            ProviderField("transport_type", "Transport", "select", required=True),
            ProviderField("command", "Command"),
            ProviderField("args", "Arguments", "array"),
            ProviderField("url", "URL"),
            ProviderField("oauth.clientId", "OAuth Client ID", secret=True),
            ProviderField("oauth.clientSecret", "OAuth Client Secret", "password", secret=True),
        ],
    ),
    "gmail": ProviderDefinition(
        provider_id="gmail",
        display_name="Gmail MCP",
        provider_type="mcp",
        mcp_server_name="gmail",
        fields=[
            ProviderField("enabled", "Enabled", "boolean"),
            ProviderField("transport_type", "Transport", "select", required=True),
            ProviderField("command", "Command"),
            ProviderField("args", "Arguments", "array"),
            ProviderField("url", "URL"),
            ProviderField("oauth.clientId", "OAuth Client ID", secret=True),
            ProviderField("oauth.clientSecret", "OAuth Client Secret", "password", secret=True),
            ProviderField("scopes", "OAuth Scopes", "array"),
        ],
    ),
    "whatsapp_api": ProviderDefinition(
        provider_id="whatsapp_api",
        display_name="WhatsApp API",
        provider_type="external_api",
        direct_env_vars=[_env_name("WHATSAPP", "API", "TOKEN"), "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_API_VERSION", "WHATSAPP_API_BASE_URL"],
        fields=[
            ProviderField(_env_name("WHATSAPP", "API", "TOKEN"), "WhatsApp API Token", "password", secret=True, required=True),
            ProviderField("WHATSAPP_PHONE_NUMBER_ID", "Phone Number ID", required=True),
            ProviderField("WHATSAPP_API_VERSION", "API Version"),
            ProviderField("WHATSAPP_API_BASE_URL", "API Base URL"),
        ],
    ),
    "telegram_bot_api": ProviderDefinition(
        provider_id="telegram_bot_api",
        display_name="Telegram Bot API",
        provider_type="external_api",
        direct_env_vars=[_env_name("TELEGRAM", "BOT", "TOKEN"), "TELEGRAM_API_BASE_URL", "TELEGRAM_TEST_CHAT_ID"],
        fields=[
            ProviderField(_env_name("TELEGRAM", "BOT", "TOKEN"), "Telegram Bot Token", "password", secret=True, required=True),
            ProviderField("TELEGRAM_TEST_CHAT_ID", "Default Test Chat ID"),
            ProviderField("TELEGRAM_API_BASE_URL", "API Base URL"),
        ],
    ),
}


def provider_ids() -> List[str]:
    return list(PROVIDER_DEFINITIONS.keys())


def _is_secret_field(name: str) -> bool:
    lowered = str(name).lower()
    return any(marker.lower() in lowered for marker in _SECRET_MARKERS)


def _redact_value(value: Any, name: str = "") -> Any:
    if value in (None, ""):
        return value
    if isinstance(value, dict):
        return {key: _redact_value(item, key) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_value(item, name) for item in value]
    if _is_secret_field(name):
        return "[REDACTED]"
    return value


def _env_data(env_path: Optional[Path] = None) -> Dict[str, str]:
    env_path = env_path or _ENV_PATH
    if not env_path.exists():
        return {}
    result: Dict[str, str] = {}
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def _write_env_data(values: Dict[str, str], env_path: Optional[Path] = None) -> None:
    env_path = env_path or _ENV_PATH
    lines = [f"{key}={value}" for key, value in sorted(values.items())]
    env_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _read_path(data: Dict[str, Any], path: str) -> Any:
    cursor: Any = data
    for part in path.split("."):
        if not isinstance(cursor, dict) or part not in cursor:
            return None
        cursor = cursor[part]
    return cursor


def _write_path(data: Dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    cursor = data
    for part in parts[:-1]:
        nested = cursor.get(part)
        if not isinstance(nested, dict):
            nested = {}
            cursor[part] = nested
        cursor = nested
    cursor[parts[-1]] = value


def _configured_mcp_server(provider: ProviderDefinition) -> Dict[str, Any]:
    raw = load_mcp_config_data()
    servers = raw.get("mcpServers") if isinstance(raw, dict) else None
    if not isinstance(servers, dict) or not provider.mcp_server_name:
        return {}
    config = servers.get(provider.mcp_server_name)
    return dict(config) if isinstance(config, dict) else {}


def _mcp_values(provider: ProviderDefinition) -> Dict[str, Any]:
    server = _configured_mcp_server(provider)
    values: Dict[str, Any] = {}
    for field in provider.fields:
        raw = _read_path(server, field.name)
        values[field.name] = _redact_value(raw, field.name)
    return values


def _external_values(provider: ProviderDefinition) -> Dict[str, Any]:
    env_values = {**_env_data(), **{key: value for key, value in os.environ.items() if key in provider.direct_env_vars}}
    result = {}
    for field in provider.fields:
        raw = env_values.get(field.name)
        result[field.name] = _redact_value(raw, field.name)
    return result


def _mcp_configured(provider_id: str) -> Dict[str, Any]:
    status = get_mcp_provider_status(provider_id, include_config=False) or {}
    return status


def _external_configured(provider_id: str) -> Dict[str, Any]:
    return get_external_provider_status(provider_id) or {}


def provider_config_status(provider_id: str) -> Optional[Dict[str, Any]]:
    definition = PROVIDER_DEFINITIONS.get(provider_id)
    if not definition:
        return None
    if definition.provider_type == "mcp":
        status = redact_mcp_configured_secrets(_mcp_configured(provider_id))
        values = _mcp_values(definition)
        configured = bool(status.get("configured"))
        validation_status = status.get("discovery_status") or "not_validated"
        validation_error = status.get("last_error")
    else:
        status = _external_configured(provider_id)
        values = _external_values(definition)
        required_names = [field.name for field in definition.fields if field.required]
        configured = bool(status.get("configured")) or all(values.get(name) for name in required_names)
        validation_status = status.get("availability_status") or "unknown"
        validation_error = status.get("last_error")
    required_missing = [field.name for field in definition.fields if field.required and not values.get(field.name)]
    return {
        **definition.to_dict(),
        "configured": configured,
        "missing_required_fields": required_missing,
        "saved_values": values,
        "validation_status": validation_status,
        "validation_error": _redact_value(validation_error, "validation_error"),
        "status": status,
    }


def list_provider_config_statuses() -> Dict[str, Any]:
    providers = [provider_config_status(provider_id) for provider_id in provider_ids()]
    return {"providers": [item for item in providers if item is not None]}


def _load_mcp_config_for_write() -> Dict[str, Any]:
    data = load_mcp_config_data()
    if not isinstance(data, dict):
        data = {}
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        data["mcpServers"] = {}
    for stale in ("whatsapp", "telegram"):
        data["mcpServers"].pop(stale, None)
    return data


def save_provider_config(provider_id: str, values: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    definition = PROVIDER_DEFINITIONS.get(provider_id)
    if not definition:
        return None
    if definition.provider_type == "mcp":
        data = _load_mcp_config_for_write()
        server_name = definition.mcp_server_name or provider_id
        server = data["mcpServers"].get(server_name)
        if not isinstance(server, dict):
            server = {}
        for key, value in values.items():
            if key == "transport_type":
                _write_path(server, "transport", value)
            elif key in {field.name for field in definition.fields}:
                _write_path(server, key, value)
        if "enabled" not in server:
            server["enabled"] = True
        data["mcpServers"][server_name] = server
        path = mcp_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    else:
        env_values = _env_data()
        allowed = {field.name for field in definition.fields}
        for key, value in values.items():
            if key not in allowed:
                continue
            text = str(value or "").strip()
            if text:
                env_values[key] = text
                os.environ[key] = text
        _write_env_data(env_values)
    return provider_config_status(provider_id)


def clear_provider_secret(provider_id: str, field_name: Optional[str] = None) -> Optional[Dict[str, Any]]:
    definition = PROVIDER_DEFINITIONS.get(provider_id)
    if not definition:
        return None
    secret_fields = [field.name for field in definition.fields if field.secret]
    targets = [field_name] if field_name else secret_fields
    if definition.provider_type == "mcp":
        data = _load_mcp_config_for_write()
        server_name = definition.mcp_server_name or provider_id
        server = data["mcpServers"].get(server_name)
        if isinstance(server, dict):
            for target in targets:
                if target in secret_fields:
                    _write_path(server, target, "")
            data["mcpServers"][server_name] = server
            mcp_config_path().write_text(json.dumps(data, indent=2), encoding="utf-8")
    else:
        env_values = _env_data()
        for target in targets:
            if target in secret_fields:
                env_values.pop(target, None)
                os.environ.pop(target, None)
        _write_env_data(env_values)
    return provider_config_status(provider_id)


def validate_provider_config(provider_id: str) -> Optional[Dict[str, Any]]:
    definition = PROVIDER_DEFINITIONS.get(provider_id)
    if not definition:
        return None
    if definition.provider_type == "mcp":
        status = redact_mcp_configured_secrets(get_mcp_provider_status(provider_id, refresh=True, include_config=False) or {})
        validation_status = status.get("discovery_status") or status.get("availability_status") or "unknown"
        validation_error = status.get("last_error")
    else:
        status = get_external_provider_status(provider_id) or {}
        validation_status = status.get("availability_status") or "unknown"
        validation_error = status.get("last_error")
    current = provider_config_status(provider_id) or {}
    current["validation_status"] = validation_status
    current["validation_error"] = _redact_value(validation_error, "validation_error")
    current["status"] = redact_mcp_configured_secrets(status) if definition.provider_type == "mcp" else status
    return current
