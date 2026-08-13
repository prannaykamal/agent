import json
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from src.mcp_gateway.protocol.json_rpc import parse_json_rpc


class HTTPMCPTransport:
    """
    Streamable HTTP transport for remote MCP servers.
    POSTs JSON-RPC messages and accepts JSON or SSE responses.
    """

    def __init__(self, url: str, headers: Optional[Dict[str, str]] = None, timeout: float = 60.0):
        self.url = url
        self.headers = {str(key): str(value) for key, value in (headers or {}).items()}
        self.timeout = timeout
        self._connected = False
        self._session_id: Optional[str] = None
        self._protocol_version = "2024-11-05"

    def connect(self) -> None:
        if not self.url:
            raise RuntimeError("MCP HTTP transport is missing url.")
        self._connected = True

    def send_request(self, request_dict: Dict[str, Any]) -> Dict[str, Any]:
        if not self._connected:
            raise RuntimeError("MCP HTTP transport is not connected.")

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": self._protocol_version,
            **self.headers,
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id

        request = urllib.request.Request(
            self.url,
            data=json.dumps(request_dict).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                self._capture_session(response)
                content_type = str(response.headers.get("Content-Type") or "")
                raw = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                raise RuntimeError(
                    "MCP HTTP 401: Google sign-in required. Open Tools Ops and click Sign in with Google. "
                    "If Google shows redirect_uri_mismatch, add http://127.0.0.1:8000/api/tools/mcp/oauth/callback "
                    "to the OAuth client's Authorized redirect URIs."
                ) from exc
            detail = exc.read().decode("utf-8", errors="replace")[:400]
            raise RuntimeError(f"MCP HTTP {exc.code} from remote server: {detail or exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"MCP HTTP connection failed: {exc.reason}") from exc

        if not raw.strip():
            return {}
        if "text/event-stream" in content_type.lower():
            return self._select_sse_message(raw, request_dict.get("id"))
        return parse_json_rpc(raw)

    def close(self) -> None:
        self._connected = False
        self._session_id = None

    def _capture_session(self, response: Any) -> None:
        session_id = response.headers.get("Mcp-Session-Id") or response.headers.get("mcp-session-id")
        if session_id:
            self._session_id = session_id

    def _select_sse_message(self, raw: str, request_id: Any) -> Dict[str, Any]:
        messages = _parse_sse_jsonrpc(raw)
        if request_id is None:
            return messages[0] if messages else {}
        for message in messages:
            if message.get("id") == request_id:
                return message
        return messages[-1] if messages else {}


def _parse_sse_jsonrpc(raw: str) -> List[Dict[str, Any]]:
    messages: List[Dict[str, Any]] = []
    data_lines: List[str] = []

    def flush() -> None:
        if not data_lines:
            return
        blob = "\n".join(data_lines).strip()
        data_lines.clear()
        if not blob:
            return
        try:
            parsed = json.loads(blob)
        except json.JSONDecodeError:
            return
        if isinstance(parsed, dict):
            messages.append(parsed)

    for line in raw.splitlines():
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
        elif not line.strip():
            flush()
    flush()
    return messages
