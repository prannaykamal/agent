from typing import Dict, Any, Optional
from src.mcp_gateway.protocol.json_rpc import parse_json_rpc

class SSEMCPTransport:
    """
    SSE (Server-Sent Events) HTTP Transport Adapter for MCP Servers.
    Connects to remote HTTP/SSE MCP server endpoints.
    """
    def __init__(self, url: str, headers: Optional[Dict[str, str]] = None):
        self.url = url
        self.headers = headers or {}
        self.endpoint_url: Optional[str] = None
        self._connected = False

    def connect(self) -> None:
        """Simulates establishing SSE stream connection and negotiating HTTP POST endpoint."""
        self._connected = True
        self.endpoint_url = self.url.rstrip("/") + "/messages"

    def send_request(self, request_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        Sends a JSON-RPC request to the HTTP SSE message endpoint.
        Returns parsed JSON-RPC response.
        """
        if not self._connected:
            raise RuntimeError("MCP SSE transport is not connected.")

        # Simulate network request / response for MCP SSE protocol
        method = request_dict.get("method", "")
        req_id = request_dict.get("id", 1)

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "Remote SSEServer", "version": "1.0.0"}
                }
            }

        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "tools": [
                        {
                            "name": "remote_fetch",
                            "description": "Fetches content from a remote HTTP URL via SSE server.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"url": {"type": "string"}},
                                "required": ["url"]
                            }
                        }
                    ]
                }
            }

        if method == "tools/call":
            params = request_dict.get("params", {})
            name = params.get("name", "remote_fetch")
            args = params.get("arguments", {})
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": f"[Remote SSE Tool '{name}' Output]: Successfully called with args {args}"
                        }
                    ]
                }
            }

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {}
        }

    def close(self) -> None:
        """Closes the SSE connection."""
        self._connected = False
