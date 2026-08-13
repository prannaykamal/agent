from src.harness.graph import get_registered_tools
from src.tools.registry import get_bindable_tool_metadata


def test_t8_primary_bindable_registry_excludes_removed_and_unavailable_tools():
    tools, tool_map = get_registered_tools()
    names = {tool.name for tool in tools}
    metadata_names = {item.legacy_name for item in get_bindable_tool_metadata()}

    assert "heartbeat" in names
    assert "run_code" not in names
    assert "safe_browse_url" not in names
    assert "email_send" not in names
    assert "calendar_create_event" not in names
    assert names.issubset(metadata_names)


def test_t8_primary_registry_can_include_available_mocked_mcp_tool(monkeypatch):
    class Tool:
        name = "mock_mcp_read"
        description = "mock"

        def invoke(self, args):
            return "ok"

    monkeypatch.setattr("src.personal_os.registry.get_all_personal_os_tools", lambda: [])
    monkeypatch.setattr("src.mcp_gateway.registry.get_all_mcp_tools", lambda: [Tool()])
    tools, tool_map = get_registered_tools()
    assert [tool.name for tool in tools] == ["mock_mcp_read"]
    assert "mock_mcp_read" in tool_map