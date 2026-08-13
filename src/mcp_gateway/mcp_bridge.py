from pathlib import Path
from typing import List, Dict, Any, Optional
from langchain_core.tools import StructuredTool, BaseTool
from pydantic import create_model

from src.config import AGENT_DIR, BASE_DIR
from src.mcp_gateway.protocol.client import MCPClient
from src.mcp_gateway.protocol.factory import auth_headers_from_server_config, build_mcp_client
from src.mcp_gateway.protocol.oauth import stdio_env_with_oauth
from src.tools.mcp_provider_config import collect_mcp_secret_values, load_mcp_config_data, redact_observability_text

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
    Parses mcp_config.json, connects to defined Stdio/SSE/HTTP MCP servers,
    and returns a list of dynamic LangChain BaseTool wrappers.
    """
    explicit_config = config_path is not None
    target_config = config_path or MCP_CONFIG_PATH
    data = load_mcp_config_data(target_config)
    mcp_servers = data.get("mcpServers", {}) if isinstance(data, dict) else {}
    if not isinstance(mcp_servers, dict):
        return []

    from src.tools.mcp_provider_registry import target_mcp_provider_ids

    retired_mcp_server_names = {"whatsapp", "telegram"}
    allowed_provider_ids = set(target_mcp_provider_ids())
    tools: List[BaseTool] = []
    for server_name, server_cfg in mcp_servers.items():
        if server_name in retired_mcp_server_names:
            continue
        if not explicit_config and server_name not in allowed_provider_ids:
            continue
        if not isinstance(server_cfg, dict):
            continue
        transport_type = str(server_cfg.get("transport", "stdio")).lower()
        if transport_type not in {"stdio", "sse", "http"}:
            continue
        client: Optional[MCPClient] = None
        try:
            env = server_cfg.get("env")
            cwd = server_cfg.get("cwd")
            if server_name in {"gmail", "google_gmail", "google_calendar"} and transport_type == "stdio":
                env = stdio_env_with_oauth(env, server_cfg.get("oauth"), project_root=BASE_DIR)
                cwd = cwd or str(BASE_DIR)
            client = build_mcp_client(
                transport=transport_type,
                command=server_cfg.get("command"),
                args=server_cfg.get("args", []),
                env=env,
                cwd=cwd,
                url=server_cfg.get("url"),
                headers=auth_headers_from_server_config(server_cfg) or None,
            )
            mcp_tools = client.list_tools()
            for t in mcp_tools:
                lc_tool = create_langchain_tool_from_mcp(client=client, tool_meta=t, server_name=server_name)
                tools.append(lc_tool)
        except Exception as e:
            safe_error = redact_observability_text(str(e), extra_values=collect_mcp_secret_values(server_cfg))
            print(f"[MCP Bridge Warning] Failed to load tools from server '{server_name}': {safe_error}")

    return tools
