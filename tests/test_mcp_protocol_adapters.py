import os
import sys
import json
import pytest
from pathlib import Path

from src.mcp_gateway.protocol.json_rpc import build_request, build_notification, build_response, parse_json_rpc, next_request_id
from src.mcp_gateway.protocol.transports.sse import SSEMCPTransport
from src.mcp_gateway.protocol.transports.stdio import StdioMCPTransport
from src.mcp_gateway.protocol.client import MCPClient
from src.mcp_gateway.mcp_bridge import load_live_mcp_tools, create_langchain_tool_from_mcp

def test_json_rpc_framing():
    req = build_request("tools/list", {"limit": 10}, request_id=101)
    assert req["jsonrpc"] == "2.0"
    assert req["id"] == 101
    assert req["method"] == "tools/list"
    assert req["params"]["limit"] == 10

    notif = build_notification("notifications/initialized")
    assert "id" not in notif
    assert notif["method"] == "notifications/initialized"

    resp = build_response(101, result={"status": "ok"})
    assert resp["id"] == 101
    assert resp["result"]["status"] == "ok"

    parsed = parse_json_rpc(json.dumps(resp))
    assert parsed["result"]["status"] == "ok"

def test_sse_transport_and_mcp_client():
    transport = SSEMCPTransport(url="http://localhost:8000/sse")
    client = MCPClient(transport)

    init_res = client.connect_and_initialize()
    assert client._is_initialized is True
    assert client.server_info["name"] == "Remote SSEServer"

    tools = client.list_tools()
    assert len(tools) >= 1
    assert tools[0]["name"] == "remote_fetch"

    call_output = client.call_tool("remote_fetch", {"url": "https://example.com"})
    assert "[Remote SSE Tool 'remote_fetch' Output]" in call_output
    client.close()

def test_stdio_transport_mock(tmp_path):
    # Create a mock python MCP stdio server script
    mock_server_script = tmp_path / "mock_stdio_server.py"
    mock_server_code = """
import sys, json

def read_message():
    headers = {}
    while True:
        line = sys.stdin.readline()
        if not line:
            return None
        if line in ("\\n", "\\r\\n"):
            break
        stripped = line.strip()
        if stripped.startswith("{") and "content-length" not in headers:
            return json.loads(stripped)
        if ":" in stripped:
            key, value = stripped.split(":", 1)
            headers[key.strip().lower()] = value.strip()
    length = int(headers["content-length"])
    body = sys.stdin.read(length)
    return json.loads(body)

def write_message(payload):
    raw = json.dumps(payload)
    sys.stdout.write("Content-Length: %s\\r\\n\\r\\n%s" % (len(raw), raw))
    sys.stdout.flush()

while True:
    req = read_message()
    if req is None:
        break
    req_id = req.get("id")
    method = req.get("method", "")
    if req_id is None:
        continue

    if method == "initialize":
        res = {"jsonrpc": "2.0", "id": req_id, "result": {"serverInfo": {"name": "Mock Stdio Server"}}}
    elif method == "tools/list":
        res = {"jsonrpc": "2.0", "id": req_id, "result": {"tools": [{"name": "echo_tool", "description": "Echoes input text", "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}}]}}
    elif method == "tools/call":
        args = req.get("params", {}).get("arguments", {})
        res = {"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": f"Echo: {args.get('text', '')}"}]}}
    else:
        res = {"jsonrpc": "2.0", "id": req_id, "result": {}}
    write_message(res)
"""
    mock_server_script.write_text(mock_server_code, encoding="utf-8")

    transport = StdioMCPTransport(command=sys.executable, args=[str(mock_server_script)])
    client = MCPClient(transport)

    client.connect_and_initialize()
    assert client.server_info["name"] == "Mock Stdio Server"

    tools = client.list_tools()
    assert len(tools) == 1
    assert tools[0]["name"] == "echo_tool"

    output = client.call_tool("echo_tool", {"text": "Hello MCP Stdio"})
    assert "Echo: Hello MCP Stdio" in output

    client.close()

def test_mcp_bridge_and_langchain_wrapping(tmp_path):
    config_file = tmp_path / "mcp_config.json"
    config_content = {
        "mcpServers": {
            "test_sse": {
                "transport": "sse",
                "url": "http://localhost:8000/sse"
            }
        }
    }
    config_file.write_text(json.dumps(config_content), encoding="utf-8")

    lc_tools = load_live_mcp_tools(config_path=config_file)
    assert len(lc_tools) >= 1

    tool_names = [t.name for t in lc_tools]
    assert "test_sse_remote_fetch" in tool_names

    # Test invoking dynamically wrapped tool
    target_tool = lc_tools[0]
    out = target_tool.invoke({"url": "https://test.org"})
    assert "[Remote SSE Tool" in out


def test_stdio_resolves_npx_from_extra_bin_dirs(tmp_path, monkeypatch):
    from src.mcp_gateway.protocol.transports import command_resolve

    bin_dir = tmp_path / "bins"
    bin_dir.mkdir()
    npx = bin_dir / "npx"
    npx.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    npx.chmod(0o755)
    monkeypatch.setattr(command_resolve, "extra_bin_dirs", lambda: [str(bin_dir)])

    env = command_resolve.merge_stdio_env({"CUSTOM": "1"})
    command, args, launch_env = command_resolve.resolve_stdio_launch("npx", ["-y", "pkg"], env)
    assert command == str(npx)
    assert args == ["-y", "pkg"]
    assert launch_env["CUSTOM"] == "1"
    assert str(bin_dir) in launch_env["PATH"]


def test_uvx_falls_back_to_uv_tool_run(tmp_path, monkeypatch):
    from src.mcp_gateway.protocol.transports import command_resolve

    bin_dir = tmp_path / "bins"
    bin_dir.mkdir()
    uv = bin_dir / "uv"
    uv.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    uv.chmod(0o755)
    monkeypatch.setattr(command_resolve, "extra_bin_dirs", lambda: [str(bin_dir)])
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))

    command, args, _env = command_resolve.resolve_stdio_launch(
        "uvx",
        ["--with", "example-mcp-server", "example-mcp-server"],
        {},
    )
    assert command == str(uv)
    assert args[:2] == ["tool", "run"]
    assert args[2:] == ["--with", "example-mcp-server", "example-mcp-server"]


def test_http_transport_json_and_empty_notification(tmp_path):
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from src.mcp_gateway.protocol.transports.http import HTTPMCPTransport, _parse_sse_jsonrpc

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
                result = {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "HTTP Test Server", "version": "1.0.0"},
                }
            elif method == "tools/list":
                result = {
                    "tools": [
                        {
                            "name": "http_echo",
                            "description": "Echo",
                            "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}},
                        }
                    ]
                }
            elif method == "tools/call":
                text = payload.get("params", {}).get("arguments", {}).get("text", "")
                result = {"content": [{"type": "text", "text": f"HTTP Echo: {text}"}]}
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
        url = f"http://127.0.0.1:{server.server_port}/mcp"
        client = MCPClient(HTTPMCPTransport(url=url))
        client.connect_and_initialize()
        assert client.server_info["name"] == "HTTP Test Server"
        tools = client.list_tools()
        assert tools[0]["name"] == "http_echo"
        assert "HTTP Echo: ping" in client.call_tool("http_echo", {"text": "ping"})
        client.close()
    finally:
        server.shutdown()
        server.server_close()

    parsed = _parse_sse_jsonrpc('event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"ok":true}}\n\n')
    assert parsed[0]["result"]["ok"] is True
