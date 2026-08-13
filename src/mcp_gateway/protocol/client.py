from typing import Dict, Any, List, Union
from src.mcp_gateway.protocol.json_rpc import build_request, build_notification
from src.mcp_gateway.protocol.transports.http import HTTPMCPTransport
from src.mcp_gateway.protocol.transports.stdio import StdioMCPTransport
from src.mcp_gateway.protocol.transports.sse import SSEMCPTransport

TransportType = Union[StdioMCPTransport, SSEMCPTransport, HTTPMCPTransport]

class MCPClient:
    """
    MCP Client Session Manager.
    Manages transport lifecycle, performs MCP protocol initialization handshake,
    discovers tools ('tools/list'), and invokes tools ('tools/call').
    """
    def __init__(self, transport: TransportType):
        self.transport = transport
        self.server_info: Dict[str, Any] = {}
        self.capabilities: Dict[str, Any] = {}
        self._is_initialized = False

    def connect_and_initialize(self) -> Dict[str, Any]:
        """Connects transport and executes standard MCP initialize handshake."""
        self.transport.connect()
        init_req = build_request(
            method="initialize",
            params={
                "protocolVersion": "2024-11-05",
                "capabilities": {"roots": {"listChanged": True}},
                "clientInfo": {"name": "24x7-Personal-Assistant", "version": "1.0.0"}
            }
        )

        resp = self.transport.send_request(init_req)
        if "error" in resp:
            raise RuntimeError(f"MCP Initialize failed: {resp['error']}")

        result = resp.get("result", {})
        self.server_info = result.get("serverInfo", {})
        self.capabilities = result.get("capabilities", {})
        self._is_initialized = True

        # Send notifications/initialized per spec
        try:
            init_notif = build_notification("notifications/initialized")
            self.transport.send_request(init_notif)
        except Exception:
            pass  # Notifications may not require response

        return result

    def list_tools(self) -> List[Dict[str, Any]]:
        """Invokes MCP 'tools/list' request and returns available server tools."""
        if not self._is_initialized:
            self.connect_and_initialize()

        req = build_request(method="tools/list")
        resp = self.transport.send_request(req)
        if "error" in resp:
            raise RuntimeError(f"MCP tools/list failed: {resp['error']}")

        return resp.get("result", {}).get("tools", [])

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> str:
        """Invokes MCP 'tools/call' request for a tool and arguments."""
        if not self._is_initialized:
            self.connect_and_initialize()

        req = build_request(
            method="tools/call",
            params={
                "name": name,
                "arguments": arguments
            }
        )

        resp = self.transport.send_request(req)
        if "error" in resp:
            return f"[MCP Tool Error]: {resp['error'].get('message', 'Execution error')}"

        result = resp.get("result") if isinstance(resp.get("result"), dict) else {}
        content_list = result.get("content", [])
        output_parts = []
        for item in content_list:
            if isinstance(item, dict) and item.get("type") == "text":
                output_parts.append(item.get("text", ""))
            else:
                output_parts.append(str(item))
        text = "\n".join(output_parts) if output_parts else "[MCP Tool Completed - No output text]"
        if result.get("isError"):
            raise RuntimeError(text)
        return text

    def close(self) -> None:
        """Closes the client connection."""
        self.transport.close()
        self._is_initialized = False
