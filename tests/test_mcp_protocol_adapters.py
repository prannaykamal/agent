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

for line in sys.stdin:
    if not line.strip():
        continue
    req = json.loads(line)
    req_id = req.get("id", 1)
    method = req.get("method", "")

    if method == "initialize":
        res = {"jsonrpc": "2.0", "id": req_id, "result": {"serverInfo": {"name": "Mock Stdio Server"}}}
    elif method == "tools/list":
        res = {"jsonrpc": "2.0", "id": req_id, "result": {"tools": [{"name": "echo_tool", "description": "Echoes input text", "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}}]}}
    elif method == "tools/call":
        args = req.get("params", {}).get("arguments", {})
        res = {"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": f"Echo: {args.get('text', '')}"}]}}
    else:
        res = {"jsonrpc": "2.0", "id": req_id, "result": {}}

    sys.stdout.write(json.dumps(res) + "\\n")
    sys.stdout.flush()
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
