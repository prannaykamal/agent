import json
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from src.config import AGENT_DIR


class MCPTransportType(str, Enum):
    STDIO = "stdio"
    SSE = "sse"
    HTTP = "http"
    APP_CONNECTOR = "app_connector"
    UNKNOWN = "unknown"


class MCPCredentialStatus(str, Enum):
    CONFIGURED = "configured"
    MISSING = "missing"
    PROVIDER_MANAGED = "provider_managed"
    UNKNOWN = "unknown"


class MCPDiscoveryStatus(str, Enum):
    NOT_CONFIGURED = "not_configured"
    NOT_DISCOVERED = "not_discovered"
    DISCOVERED = "discovered"
    FAILED = "failed"
    UNSUPPORTED_TRANSPORT = "unsupported_transport"


SECRET_KEY_MARKERS = (
    "api_key",
    "token",
    "secret",
    "password",
    "credential",
    "authorization",
    "access_key",
    "access_token",
    "refresh_token",
)

TARGET_MCP_PROVIDER_ALIASES: Dict[str, List[str]] = {
    "search_tavily": ["search_tavily", "tavily"],
    "search_duckduckgo": ["search_duckduckgo", "duckduckgo", "duckduckgo.query"],
    "google_calendar": ["google_calendar", "calendar"],
    "gmail": ["gmail", "google_gmail"],
}


@dataclass(frozen=True)
class MCPProviderConfig:
    provider_id: str
    display_name: str
    enabled: bool = False
    transport_type: MCPTransportType = MCPTransportType.UNKNOWN
    command: Optional[str] = None
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    url: Optional[str] = None
    redaction_values: Tuple[str, ...] = field(default_factory=tuple)
    expected_tool_hints: List[str] = field(default_factory=list)
    credential_status: MCPCredentialStatus = MCPCredentialStatus.MISSING
    discovery_status: MCPDiscoveryStatus = MCPDiscoveryStatus.NOT_CONFIGURED
    last_discovered_at: Optional[str] = None
    last_error: Optional[str] = None

    @property
    def availability_status(self) -> str:
        if not self.enabled or self.discovery_status == MCPDiscoveryStatus.NOT_CONFIGURED:
            return "unavailable"
        if self.discovery_status == MCPDiscoveryStatus.DISCOVERED:
            return "available"
        return "unavailable"

    @property
    def is_configured(self) -> bool:
        return self.discovery_status != MCPDiscoveryStatus.NOT_CONFIGURED

    def with_discovery(
        self,
        *,
        discovery_status: MCPDiscoveryStatus,
        last_error: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> "MCPProviderConfig":
        timestamp = (now or datetime.now(timezone.utc)).replace(microsecond=0).isoformat()
        return replace(
            self,
            discovery_status=discovery_status,
            last_discovered_at=timestamp,
            last_error=redact_observability_text(last_error, extra_values=self.redaction_values) if last_error else None,
        )

    def to_status_dict(self, include_config: bool = False) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "provider_id": self.provider_id,
            "display_name": self.display_name,
            "enabled": self.enabled,
            "transport_type": self.transport_type.value,
            "credential_status": self.credential_status.value,
            "discovery_status": self.discovery_status.value,
            "availability_status": self.availability_status,
            "configured": self.is_configured,
            "expected_tool_hints": list(self.expected_tool_hints),
            "last_discovered_at": self.last_discovered_at,
            "last_error": redact_observability_text(self.last_error, extra_values=self.redaction_values),
        }
        if include_config:
            data.update(
                {
                    "command": self.command,
                    "args": list(self.args),
                    "env": redact_observability_value(self.env, extra_values=self.redaction_values),
                    "url": redact_url(self.url, extra_values=self.redaction_values),
                }
            )
        return data


TARGET_MCP_PROVIDER_DEFAULTS: Dict[str, MCPProviderConfig] = {
    "search_tavily": MCPProviderConfig(
        provider_id="search_tavily",
        display_name="Tavily Search MCP",
        expected_tool_hints=["search", "tavily_search"],
    ),
    "search_duckduckgo": MCPProviderConfig(
        provider_id="search_duckduckgo",
        display_name="DuckDuckGo Search MCP",
        expected_tool_hints=["search", "duckduckgo.query"],
    ),
    "google_calendar": MCPProviderConfig(
        provider_id="google_calendar",
        display_name="Google Calendar MCP",
        expected_tool_hints=["calendar", "events"],
    ),
    "gmail": MCPProviderConfig(
        provider_id="gmail",
        display_name="Gmail MCP",
        expected_tool_hints=["mail", "messages", "send"],
    ),
}


def _key_has_secret_marker(key: str) -> bool:
    lowered = str(key or "").lower()
    return any(marker in lowered for marker in SECRET_KEY_MARKERS)


def _is_redaction_candidate(value: Any, *, min_length: int = 8) -> bool:
    text = str(value or "").strip()
    if len(text) < min_length:
        return False
    lowered = text.lower()
    if lowered.startswith(("your_", "paste_", "placeholder", "changeme", "replace_me")):
        return False
    return True


def _scalar_secret_values(value: Any) -> Tuple[str, ...]:
    if isinstance(value, str) and _is_redaction_candidate(value):
        return (value,)
    if isinstance(value, (int, float)) and _is_redaction_candidate(value):
        return (str(value),)
    return ()


def _collect_all_scalar_values(value: Any) -> Tuple[str, ...]:
    values: List[str] = []
    if isinstance(value, dict):
        for item in value.values():
            values.extend(_collect_all_scalar_values(item))
    elif isinstance(value, list):
        for item in value:
            values.extend(_collect_all_scalar_values(item))
    else:
        values.extend(_scalar_secret_values(value))
    return tuple(values)


def collect_mcp_secret_values(value: Any, *, key: str = "") -> Tuple[str, ...]:
    values: List[str] = []
    if isinstance(value, dict):
        for child_key, child_value in value.items():
            child_key_text = str(child_key)
            if _key_has_secret_marker(child_key_text) or child_key_text.lower() in {"env", "headers", "oauth"}:
                values.extend(_collect_all_scalar_values(child_value))
            else:
                values.extend(collect_mcp_secret_values(child_value, key=child_key_text))
    elif isinstance(value, list):
        for item in value:
            values.extend(collect_mcp_secret_values(item, key=key))
    elif _key_has_secret_marker(key):
        values.extend(_scalar_secret_values(value))
    seen = set()
    deduped = []
    for item in values:
        if item not in seen:
            seen.add(item)
            deduped.append(item)
    return tuple(deduped)


def redact_observability_text(
    value: Optional[str],
    *,
    limit: int = 240,
    extra_values: Iterable[str] = (),
) -> Optional[str]:
    if value is None:
        return None
    text = str(value)
    for secret_value in sorted(set(extra_values), key=len, reverse=True):
        if _is_redaction_candidate(secret_value):
            text = text.replace(str(secret_value), "[REDACTED]")
    if any(marker in text.lower() for marker in SECRET_KEY_MARKERS):
        return "[REDACTED]"
    if len(text) > limit:
        return text[:limit] + "..."
    return text


def redact_observability_value(value: Any, *, key: str = "", extra_values: Iterable[str] = ()) -> Any:
    if _key_has_secret_marker(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        redacted: Dict[str, Any] = {}
        for child_key, item in value.items():
            redacted[str(child_key)] = redact_observability_value(item, key=str(child_key), extra_values=extra_values)
        return redacted
    if isinstance(value, list):
        return [redact_observability_value(item, key=key, extra_values=extra_values) for item in value]
    if isinstance(value, str):
        return redact_observability_text(value, extra_values=extra_values)
    return value


def redact_url(url: Optional[str], *, extra_values: Iterable[str] = ()) -> Optional[str]:
    if not url:
        return url
    text = redact_observability_text(str(url), extra_values=extra_values) or ""
    if "@" in text:
        scheme, _, rest = text.partition("://")
        _, _, host = rest.rpartition("@")
        return f"{scheme}://[REDACTED]@{host}" if scheme and host else "[REDACTED]"
    return text


def mcp_config_path() -> Path:
    return AGENT_DIR / "mcp_config.json"


def load_mcp_config_data(config_path: Optional[Path] = None) -> Dict[str, Any]:
    path = Path(config_path) if config_path else mcp_config_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def configured_mcp_secret_values(config_path: Optional[Path] = None) -> Tuple[str, ...]:
    return collect_mcp_secret_values(load_mcp_config_data(config_path))


def redact_mcp_configured_secrets(
    value: Any,
    *,
    config_path: Optional[Path] = None,
    extra_values: Iterable[str] = (),
) -> Any:
    values = tuple(extra_values) + configured_mcp_secret_values(config_path)
    return redact_observability_value(value, extra_values=values)


def redact_mcp_configured_secret_text(
    value: Optional[str],
    *,
    config_path: Optional[Path] = None,
    extra_values: Iterable[str] = (),
    limit: int = 240,
) -> Optional[str]:
    values = tuple(extra_values) + configured_mcp_secret_values(config_path)
    return redact_observability_text(value, extra_values=values, limit=limit)


def _transport_type(raw_value: Any) -> MCPTransportType:
    try:
        return MCPTransportType(str(raw_value or "stdio").lower())
    except ValueError:
        return MCPTransportType.UNKNOWN


def _credential_status(server_config: Dict[str, Any], transport: MCPTransportType) -> MCPCredentialStatus:
    if bool(server_config.get("provider_managed")) or transport == MCPTransportType.APP_CONNECTOR:
        return MCPCredentialStatus.PROVIDER_MANAGED
    env = server_config.get("env")
    if isinstance(env, dict) and env:
        return MCPCredentialStatus.CONFIGURED
    if server_config.get("url") or server_config.get("command"):
        return MCPCredentialStatus.CONFIGURED
    return MCPCredentialStatus.UNKNOWN


def _configured_provider_id(server_name: str) -> Optional[str]:
    clean = str(server_name or "").strip().lower()
    for provider_id, aliases in TARGET_MCP_PROVIDER_ALIASES.items():
        if clean in aliases:
            return provider_id
    return None


def load_target_mcp_provider_configs(config_path: Optional[Path] = None) -> Dict[str, MCPProviderConfig]:
    configs = dict(TARGET_MCP_PROVIDER_DEFAULTS)
    raw = load_mcp_config_data(config_path)
    servers = raw.get("mcpServers") if isinstance(raw, dict) else None
    if not isinstance(servers, dict):
        return configs

    for server_name, server_config in servers.items():
        if not isinstance(server_config, dict):
            continue
        provider_id = _configured_provider_id(server_name)
        if not provider_id:
            continue
        base = configs[provider_id]
        transport = _transport_type(server_config.get("transport"))
        configs[provider_id] = replace(
            base,
            enabled=bool(server_config.get("enabled", True)),
            transport_type=transport,
            command=server_config.get("command"),
            args=list(server_config.get("args") or []),
            env=dict(server_config.get("env") or {}),
            url=server_config.get("url"),
            redaction_values=collect_mcp_secret_values(server_config),
            credential_status=_credential_status(server_config, transport),
            discovery_status=MCPDiscoveryStatus.NOT_DISCOVERED,
            last_error=None,
        )
    return configs
