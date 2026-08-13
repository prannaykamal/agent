from typing import Any, Dict, Mapping, Optional, Sequence

from src.mcp_gateway.protocol.client import MCPClient
from src.mcp_gateway.protocol.transports.http import HTTPMCPTransport
from src.mcp_gateway.protocol.transports.sse import SSEMCPTransport
from src.mcp_gateway.protocol.transports.stdio import StdioMCPTransport


def build_mcp_client(
    *,
    transport: str,
    command: Optional[str] = None,
    args: Optional[Sequence[str]] = None,
    env: Optional[Mapping[str, str]] = None,
    cwd: Optional[str] = None,
    url: Optional[str] = None,
    headers: Optional[Mapping[str, str]] = None,
) -> MCPClient:
    kind = str(transport or "stdio").lower()
    header_map: Optional[Dict[str, str]] = dict(headers) if headers else None
    if kind == "stdio":
        if not command:
            raise RuntimeError("Configured stdio MCP provider is missing command.")
        return MCPClient(StdioMCPTransport(command=command, args=list(args or []), env=dict(env) if env else None, cwd=cwd))
    if kind == "sse":
        if not url:
            raise RuntimeError("Configured SSE MCP provider is missing url.")
        return MCPClient(SSEMCPTransport(url=url, headers=header_map))
    if kind == "http":
        if not url:
            raise RuntimeError("Configured HTTP MCP provider is missing url.")
        return MCPClient(HTTPMCPTransport(url=url, headers=header_map))
    raise RuntimeError(f"Unsupported MCP transport for automatic discovery: {kind}")


def auth_headers_from_server_config(server_cfg: Mapping[str, Any]) -> Dict[str, str]:
    headers: Dict[str, str] = {}
    raw_headers = server_cfg.get("headers")
    if isinstance(raw_headers, dict):
        headers.update({str(key): str(value) for key, value in raw_headers.items() if value is not None})
    oauth = server_cfg.get("oauth")
    token = None
    if isinstance(oauth, dict):
        token = oauth.get("accessToken") or oauth.get("access_token")
    if token and "Authorization" not in headers:
        headers["Authorization"] = f"Bearer {token}"
    return headers
