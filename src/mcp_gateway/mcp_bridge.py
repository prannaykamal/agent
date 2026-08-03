import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from langchain_core.tools import StructuredTool, BaseTool
from pydantic import create_model

from src.config import AGENT_DIR
from src.mcp_gateway.protocol.transports.stdio import StdioMCPTransport
from src.mcp_gateway.protocol.transports.sse import SSEMCPTransport
from src.mcp_gateway.protocol.client import MCPClient

MCP_CONFIG_PATH = AGENT_DIR / "mcp_config.json"

def create_langchain_tool_from_mcp(client: MCPClient, tool_meta: Dict[str, Any], server_name: str) -> BaseTool:
    """Dynamically creates a LangChain StructuredTool wrapping an MCP server tool call."""
    name = tool_meta["name"]
    description = tool_meta.get("description", f"MCP Tool '{name}' from server '{server_name}'")
    input_schema = tool_meta.get("inputSchema", {})

    # Build Pydantic args schema from JSON schema properties
    properties = input_schema.get("properties", {})
    required_fields = set(input_schema.get("required", []))

    field_definitions = {}
    for prop_name, prop_spec in properties.items():
        prop_type = prop_spec.get("type", "string")
        py_type = str if prop_type == "string" else (int if prop_type in ("integer", "number") else (bool if prop_type == "boolean" else Any))
        default_val = ... if prop_name in required_fields else None
        field_definitions[prop_name] = (py_type, default_val)

    ArgsModel = create_model(f"{server_name}_{name}_args", **field_definitions) if field_definitions else None

    def _run_tool(**kwargs) -> str:
        return client.call_tool(name=name, arguments=kwargs)

    tool_name_prefixed = f"{server_name}_{name}" if not name.startswith(server_name) else name

    if ArgsModel:
        return StructuredTool.from_function(
            func=_run_tool,
            name=tool_name_prefixed,
            description=description,
            args_schema=ArgsModel
        )

    return StructuredTool.from_function(
        func=_run_tool,
        name=tool_name_prefixed,
        description=description
    )

def load_live_mcp_tools(config_path: Optional[Path] = None) -> List[BaseTool]:
    """
    Parses mcp_config.json, connects to defined Stdio/SSE MCP servers,
    and returns a list of dynamic LangChain BaseTool wrappers.
    """
    target_config = config_path or MCP_CONFIG_PATH
    if not target_config.exists():
        return []

    try:
        content = target_config.read_text(encoding="utf-8")
        data = json.loads(content)
        mcp_servers = data.get("mcpServers", {})
    except Exception:
        return []

    tools: List[BaseTool] = []
    for server_name, server_cfg in mcp_servers.items():
        transport_type = server_cfg.get("transport", "stdio").lower()
        client: Optional[MCPClient] = None

        if transport_type == "stdio":
            cmd = server_cfg.get("command")
            if not cmd:
                continue
            args = server_cfg.get("args", [])
            env = server_cfg.get("env")
            cwd = server_cfg.get("cwd")
            transport = StdioMCPTransport(command=cmd, args=args, env=env, cwd=cwd)
            client = MCPClient(transport)

        elif transport_type == "sse":
            url = server_cfg.get("url")
            if not url:
                continue
            headers = server_cfg.get("headers")
            transport = SSEMCPTransport(url=url, headers=headers)
            client = MCPClient(transport)

        if client:
            try:
                mcp_tools = client.list_tools()
                for t in mcp_tools:
                    lc_tool = create_langchain_tool_from_mcp(client=client, tool_meta=t, server_name=server_name)
                    tools.append(lc_tool)
            except Exception as e:
                print(f"[MCP Bridge Warning] Failed to load tools from server '{server_name}': {str(e)}")

    return tools
