import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from src.mcp_gateway.protocol.client import MCPClient
from src.mcp_gateway.protocol.factory import build_mcp_client
from src.tools.mcp_provider_config import (
    MCPDiscoveryStatus,
    MCPProviderConfig,
    MCPTransportType,
    TARGET_MCP_PROVIDER_DEFAULTS,
    load_target_mcp_provider_configs,
)
from src.tools.mcp_schema import normalize_mcp_tool_metadata
from src.tools.registry_types import ToolMetadata

MCPClientFactory = Callable[[MCPProviderConfig], Any]


@dataclass(frozen=True)
class MCPProviderDiscoveryResult:
    provider: MCPProviderConfig
    tools: List[ToolMetadata] = field(default_factory=list)

    def to_status_dict(self, include_config: bool = False, include_tools: bool = True) -> Dict[str, Any]:
        data = self.provider.to_status_dict(include_config=include_config)
        data["tool_count"] = len(self.tools)
        if include_tools:
            data["tools"] = [tool.to_dict() for tool in self.tools]
        return data


_DISCOVERY_CACHE: Dict[str, MCPProviderDiscoveryResult] = {}


def target_mcp_provider_ids() -> List[str]:
    return list(TARGET_MCP_PROVIDER_DEFAULTS.keys())


def _provider_cache_key(provider: MCPProviderConfig) -> str:
    """Bind cache entries to config identity so a later config cannot reuse stale discovery."""
    env_blob = repr(sorted((provider.env or {}).items()))
    env_fingerprint = hashlib.sha256(env_blob.encode("utf-8")).hexdigest()[:16]
    headers_blob = repr(sorted((provider.headers or {}).items()))
    headers_fingerprint = hashlib.sha256(headers_blob.encode("utf-8")).hexdigest()[:16]
    oauth_blob = repr(sorted((provider.oauth or {}).items()))
    oauth_fingerprint = hashlib.sha256(oauth_blob.encode("utf-8")).hexdigest()[:16]
    return "|".join(
        (
            provider.provider_id,
            str(bool(provider.enabled)),
            str(provider.transport_type.value if provider.transport_type else ""),
            str(provider.command or ""),
            ",".join(provider.args or []),
            str(provider.url or ""),
            env_fingerprint,
            headers_fingerprint,
            oauth_fingerprint,
        )
    )


def _store_discovery(provider: MCPProviderConfig, result: MCPProviderDiscoveryResult) -> MCPProviderDiscoveryResult:
    _DISCOVERY_CACHE[_provider_cache_key(provider)] = result
    return result


def _cached_discovery(provider: MCPProviderConfig) -> Optional[MCPProviderDiscoveryResult]:
    return _DISCOVERY_CACHE.get(_provider_cache_key(provider))


_DISCOVERABLE_TRANSPORTS = {
    MCPTransportType.STDIO,
    MCPTransportType.SSE,
    MCPTransportType.HTTP,
}


def _provider_headers(provider: MCPProviderConfig) -> Dict[str, str]:
    headers = dict(provider.headers or {})
    token = (provider.oauth or {}).get("accessToken") or (provider.oauth or {}).get("access_token")
    if token and "Authorization" not in headers:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _provider_stdio_env(provider: MCPProviderConfig) -> Dict[str, str]:
    from src.config import BASE_DIR
    from src.mcp_gateway.protocol.oauth import OAUTH_GOOGLE_PROVIDERS, stdio_env_with_oauth

    if provider.provider_id in OAUTH_GOOGLE_PROVIDERS:
        return stdio_env_with_oauth(provider.env, provider.oauth, project_root=BASE_DIR)
    return dict(provider.env or {})


def _build_mcp_client(provider: MCPProviderConfig) -> MCPClient:
    from src.config import BASE_DIR
    from src.mcp_gateway.protocol.oauth import OAUTH_GOOGLE_PROVIDERS, ensure_fresh_access_token

    provider = ensure_fresh_access_token(provider)
    cwd = None
    env = provider.env or None
    if provider.transport_type == MCPTransportType.STDIO:
        env = _provider_stdio_env(provider)
        if provider.provider_id in OAUTH_GOOGLE_PROVIDERS:
            cwd = str(BASE_DIR)
    return build_mcp_client(
        transport=provider.transport_type.value,
        command=provider.command,
        args=provider.args,
        env=env,
        cwd=cwd,
        url=provider.url,
        headers=_provider_headers(provider) or None,
    )


def discover_mcp_provider(
    provider: MCPProviderConfig,
    *,
    client_factory: Optional[MCPClientFactory] = None,
    now: Optional[datetime] = None,
) -> MCPProviderDiscoveryResult:
    if not provider.enabled or provider.discovery_status == MCPDiscoveryStatus.NOT_CONFIGURED:
        return MCPProviderDiscoveryResult(provider=provider, tools=[])

    if provider.transport_type not in _DISCOVERABLE_TRANSPORTS and client_factory is None:
        discovered = provider.with_discovery(
            discovery_status=MCPDiscoveryStatus.UNSUPPORTED_TRANSPORT,
            last_error=f"Transport {provider.transport_type.value} requires provider-managed validation.",
            now=now,
        )
        result = MCPProviderDiscoveryResult(provider=discovered, tools=[])
        return _store_discovery(provider, result)

    client = None
    try:
        client = client_factory(provider) if client_factory else _build_mcp_client(provider)
        raw_tools = client.list_tools()
        if not isinstance(raw_tools, list):
            raise RuntimeError("MCP tools/list response did not return a tool list.")
        discovered_provider = provider.with_discovery(
            discovery_status=MCPDiscoveryStatus.DISCOVERED,
            now=now,
        )
        tools = [
            normalize_mcp_tool_metadata(discovered_provider, tool)
            for tool in raw_tools
            if isinstance(tool, dict) and str(tool.get("name") or "").strip()
        ]
        result = MCPProviderDiscoveryResult(provider=discovered_provider, tools=tools)
        return _store_discovery(provider, result)
    except Exception as exc:
        failed_provider = provider.with_discovery(
            discovery_status=MCPDiscoveryStatus.FAILED,
            last_error=str(exc),
            now=now,
        )
        result = MCPProviderDiscoveryResult(provider=failed_provider, tools=[])
        return _store_discovery(provider, result)
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass


def get_mcp_provider_results(
    *,
    config_path: Optional[Path] = None,
    refresh: bool = False,
    client_factory: Optional[MCPClientFactory] = None,
    now: Optional[datetime] = None,
) -> List[MCPProviderDiscoveryResult]:
    configs = load_target_mcp_provider_configs(config_path)
    results: List[MCPProviderDiscoveryResult] = []
    for provider_id in target_mcp_provider_ids():
        config = configs[provider_id]
        cached = _cached_discovery(config)
        if not refresh and config.is_configured and cached is not None:
            results.append(cached)
            continue
        if refresh and config.is_configured:
            results.append(discover_mcp_provider(config, client_factory=client_factory, now=now))
        else:
            if cached is not None and config.is_configured:
                results.append(cached)
            else:
                results.append(MCPProviderDiscoveryResult(provider=config, tools=[]))
    return results


def get_mcp_provider_statuses(
    *,
    config_path: Optional[Path] = None,
    refresh: bool = False,
    include_config: bool = False,
    client_factory: Optional[MCPClientFactory] = None,
) -> List[Dict[str, Any]]:
    return [
        result.to_status_dict(include_config=include_config)
        for result in get_mcp_provider_results(
            config_path=config_path,
            refresh=refresh,
            client_factory=client_factory,
            now=datetime.now(timezone.utc),
        )
    ]


def get_mcp_provider_status(
    provider_id: str,
    *,
    config_path: Optional[Path] = None,
    refresh: bool = False,
    include_config: bool = False,
    client_factory: Optional[MCPClientFactory] = None,
) -> Optional[Dict[str, Any]]:
    clean_id = str(provider_id or "").strip()
    for status in get_mcp_provider_statuses(
        config_path=config_path,
        refresh=refresh,
        include_config=include_config,
        client_factory=client_factory,
    ):
        if status["provider_id"] == clean_id:
            return status
    return None


def get_provider_managed_mcp_tool_metadata(
    *,
    config_path: Optional[Path] = None,
    refresh: bool = False,
    client_factory: Optional[MCPClientFactory] = None,
) -> List[ToolMetadata]:
    tools: List[ToolMetadata] = []
    for result in get_mcp_provider_results(
        config_path=config_path,
        refresh=refresh,
        client_factory=client_factory,
        now=datetime.now(timezone.utc),
    ):
        if result.provider.discovery_status == MCPDiscoveryStatus.DISCOVERED:
            tools.extend([tool for tool in result.tools if tool.enabled])
    return tools


def clear_mcp_provider_discovery_cache() -> None:
    _DISCOVERY_CACHE.clear()
