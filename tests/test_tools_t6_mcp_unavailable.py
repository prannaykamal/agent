import json

from src.tools.mcp_provider_config import MCPDiscoveryStatus
from src.tools.mcp_provider_registry import clear_mcp_provider_discovery_cache, get_mcp_provider_statuses


class FakeMCPClient:
    def __init__(self, exc):
        self.exc = exc

    def list_tools(self):
        raise self.exc

    def close(self):
        pass


def test_t6_missing_provider_config_is_safe_unavailable_state(tmp_path):
    clear_mcp_provider_discovery_cache()
    statuses = get_mcp_provider_statuses(config_path=tmp_path / "missing.json", refresh=False)

    assert len(statuses) == 4
    assert all(status["availability_status"] == "unavailable" for status in statuses)
    assert all(status["discovery_status"] == MCPDiscoveryStatus.NOT_CONFIGURED.value for status in statuses)
    assert all(status["tool_count"] == 0 for status in statuses)


def test_t6_discovery_failure_is_redacted_and_non_fatal(tmp_path):
    clear_mcp_provider_discovery_cache()
    config_file = tmp_path / "mcp_config.json"
    config_file.write_text(
        json.dumps({"mcpServers": {"gmail": {"transport": "stdio", "command": "fake-gmail"}}}),
        encoding="utf-8",
    )

    statuses = get_mcp_provider_statuses(
        config_path=config_file,
        refresh=True,
        client_factory=lambda _provider: FakeMCPClient(RuntimeError("authorization token should not leak")),
    )
    gmail = {status["provider_id"]: status for status in statuses}["gmail"]

    assert gmail["availability_status"] == "unavailable"
    assert gmail["discovery_status"] == MCPDiscoveryStatus.FAILED.value
    assert gmail["last_error"] == "[REDACTED]"
    assert "should not leak" not in str(gmail)


def test_t6_unsupported_transport_is_unavailable_without_startup_failure(tmp_path):
    clear_mcp_provider_discovery_cache()
    config_file = tmp_path / "mcp_config.json"
    config_file.write_text(
        json.dumps({"mcpServers": {"google_calendar": {"transport": "app_connector", "provider_managed": True}}}),
        encoding="utf-8",
    )

    statuses = get_mcp_provider_statuses(config_path=config_file, refresh=True)
    google_calendar = {status["provider_id"]: status for status in statuses}["google_calendar"]

    assert google_calendar["availability_status"] == "unavailable"
    assert google_calendar["discovery_status"] == MCPDiscoveryStatus.UNSUPPORTED_TRANSPORT.value


def test_t6_http_transport_discovers_via_streamable_http(tmp_path):
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            return

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or "0")
            payload = json.loads(self.rfile.read(length) or b"{}")
            req_id = payload.get("id")
            method = payload.get("method")
            if req_id is None:
                self.send_response(202)
                self.end_headers()
                return
            if method == "initialize":
                result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "Gmail HTTP"}}
            elif method == "tools/list":
                result = {"tools": [{"name": "gmail_search", "inputSchema": {"type": "object"}}]}
            else:
                result = {}
            body = json.dumps({"jsonrpc": "2.0", "id": req_id, "result": result}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        config_file = tmp_path / "mcp_config.json"
        config_file.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "gmail": {
                            "transport": "http",
                            "url": f"http://127.0.0.1:{server.server_port}/mcp",
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        statuses = get_mcp_provider_statuses(config_path=config_file, refresh=True)
        gmail = {status["provider_id"]: status for status in statuses}["gmail"]
        assert gmail["discovery_status"] == MCPDiscoveryStatus.DISCOVERED.value
        assert gmail["availability_status"] == "available"
        assert gmail["tool_count"] == 1
    finally:
        server.shutdown()
        server.server_close()
