import json

from src.tools.mcp_provider_config import (
    MCPDiscoveryStatus,
    MCPCredentialStatus,
    MCPTransportType,
    load_target_mcp_provider_configs,
)
from src.tools.mcp_provider_registry import clear_mcp_provider_discovery_cache, target_mcp_provider_ids


def test_t6_all_target_provider_ids_are_represented_without_config(tmp_path):
    clear_mcp_provider_discovery_cache()
    configs = load_target_mcp_provider_configs(tmp_path / "missing.json")

    assert set(target_mcp_provider_ids()) == {
        "search_tavily",
        "search_duckduckgo",
        "google_calendar",
        "gmail",
    }
    assert set(configs) == set(target_mcp_provider_ids())
    for provider in configs.values():
        assert provider.enabled is False
        assert provider.discovery_status == MCPDiscoveryStatus.NOT_CONFIGURED
        assert provider.availability_status == "unavailable"


def test_t6_target_provider_config_is_loaded_from_mcp_config(tmp_path):
    config_file = tmp_path / "mcp_config.json"
    config_file.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "gmail": {
                        "transport": "stdio",
                        "command": "gmail-mcp",
                        "args": ["--safe"],
                        "env": {"GMAIL_TOKEN": "super-secret"},
                    },
                    "duckduckgo": {
                        "transport": "sse",
                        "url": "http://localhost:9000/sse",
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    configs = load_target_mcp_provider_configs(config_file)

    assert configs["gmail"].enabled is True
    assert configs["gmail"].transport_type == MCPTransportType.STDIO
    assert configs["gmail"].command == "gmail-mcp"
    assert configs["gmail"].credential_status == MCPCredentialStatus.CONFIGURED
    assert configs["gmail"].discovery_status == MCPDiscoveryStatus.NOT_DISCOVERED
    assert configs["search_duckduckgo"].transport_type == MCPTransportType.SSE
    assert configs["search_tavily"].discovery_status == MCPDiscoveryStatus.NOT_CONFIGURED


def test_t6_http_config_and_json_comments_are_loaded(tmp_path):
    config_file = tmp_path / "mcp_config.json"
    config_file.write_text(
        "{\n"
        "  // operator note\n"
        '  "mcpServers": {\n'
        '    "gmail": {\n'
        '      "transport": "http",\n'
        '      "url": "https://gmailmcp.googleapis.com/mcp/v1",\n'
        '      "oauth": {"clientId": "demo-client", "clientSecret": "super-secret"}\n'
        "    }\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )

    configs = load_target_mcp_provider_configs(config_file)
    assert configs["gmail"].transport_type == MCPTransportType.HTTP
    assert configs["gmail"].url.endswith("/mcp/v1")
    assert configs["gmail"].oauth["clientId"] == "demo-client"
    assert configs["gmail"].credential_status == MCPCredentialStatus.CONFIGURED
    status = configs["gmail"].to_status_dict(include_config=True)
    assert "super-secret" not in str(status)


def test_t6_provider_status_redacts_config_secrets(tmp_path):
    config_file = tmp_path / "mcp_config.json"
    config_file.write_text(
        json.dumps({"mcpServers": {"gmail": {"command": "gmail-mcp", "env": {"ACCESS_TOKEN": "abc"}}}}),
        encoding="utf-8",
    )

    provider = load_target_mcp_provider_configs(config_file)["gmail"]
    status = provider.to_status_dict(include_config=True)

    assert status["env"]["ACCESS_TOKEN"] == "[REDACTED]"
    assert "abc" not in str(status)
