from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from src.mcp_gateway.protocol.client import MCPClient
from src.mcp_gateway.protocol.transports.sse import SSEMCPTransport
from src.mcp_gateway.protocol.transports.stdio import StdioMCPTransport
from src.tools.mcp_provider_config import (
    MCPDiscoveryStatus,
    MCPProviderConfig,
    MCPTransportType,
    TARGET_MCP_PROVIDER_DEFAULTS,
    load_target_mcp_provider_configs,
    redact_observability_text,
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


def _build_mcp_client(provider: MCPProviderConfig) -> MCPClient:
    if provider.transport_type == MCPTransportType.STDIO:
        if not provider.command:
            raise RuntimeError("Configured stdio MCP provider is missing command.")
        return MCPClient(
            StdioMCPTransport(
                command=provider.command,
                args=provider.args,
                env=provider.env or None,
            )
        )
    if provider.transport_type == MCPTransportType.SSE:
        if not provider.url:
            raise RuntimeError("Configured SSE MCP provider is missing url.")
        return MCPClient(SSEMCPTransport(url=provider.url))
    raise RuntimeError(f"Unsupported MCP transport for automatic discovery: {provider.transport_type.value}")


def discover_mcp_provider(
    provider: MCPProviderConfig,
    *,
    client_factory: Optional[MCPClientFactory] = None,
    now: Optional[datetime] = None,
) -> MCPProviderDiscoveryResult:
    if not provider.enabled or provider.discovery_status == MCPDiscoveryStatus.NOT_CONFIGURED:
        return MCPProviderDiscoveryResult(provider=provider, tools=[])

    if provider.transport_type not in {MCPTransportType.STDIO, MCPTransportType.SSE} and client_factory is None:
        discovered = provider.with_discovery(
            discovery_status=MCPDiscoveryStatus.UNSUPPORTED_TRANSPORT,
            last_error=f"Transport {provider.transport_type.value} requires provider-managed validation.",
            now=now,
        )
        result = MCPProviderDiscoveryResult(provider=discovered, tools=[])
        _DISCOVERY_CACHE[provider.provider_id] = result
        return result

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
        _DISCOVERY_CACHE[provider.provider_id] = result
        return result
    except Exception as exc:
        failed_provider = provider.with_discovery(
            discovery_status=MCPDiscoveryStatus.FAILED,
            last_error=str(exc),
            now=now,
        )
        result = MCPProviderDiscoveryResult(provider=failed_provider, tools=[])
        _DISCOVERY_CACHE[provider.provider_id] = result
        return result
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
        if not refresh and config.is_configured and provider_id in _DISCOVERY_CACHE:
            results.append(_DISCOVERY_CACHE[provider_id])
            continue
        if refresh and config.is_configured:
            results.append(discover_mcp_provider(config, client_factory=client_factory, now=now))
        else:
            cached_or_config = _DISCOVERY_CACHE.get(provider_id)
            if cached_or_config and config.is_configured:
                results.append(cached_or_config)
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
