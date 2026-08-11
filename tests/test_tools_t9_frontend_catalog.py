from pathlib import Path


def test_t9_tools_catalog_groups_final_architecture():
    text = Path("frontend/src/components/ToolsCockpit.jsx").read_text(encoding="utf-8")
    assert "/api/tools" in text
    assert "/api/tools/observability/overview" in text
    assert "Personal OS" in text
    assert "Cron Boundary" in text
    assert "Provider-managed MCP Available" in text
    assert "Unavailable MCP Providers/Tools" in text
    assert "Removed/Blocked Tools" in text
    assert "implementation_type" in text
    assert "approval_policy" in text
    assert "read_write_capability" in text


def test_t9_overview_text_uses_final_tool_architecture():
    text = Path("frontend/src/components/OverviewCockpit.jsx").read_text(encoding="utf-8")
    assert "Personal OS + cron + provider-managed MCP" in text
    assert "22 OS + MCP Gateway" not in text
    assert "REAL API" not in text
    assert "LOCAL/DEFERRED" not in text