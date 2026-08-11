from pathlib import Path


def test_t9_tools_ops_component_exists_and_fetches_read_only_endpoints():
    text = Path("frontend/src/components/ToolsOpsCockpit.jsx").read_text(encoding="utf-8")
    assert "export default function ToolsOpsCockpit" in text
    assert "window.ToolsOpsCockpit" in text
    for endpoint in [
        "/api/tools/observability/overview",
        "/api/tools/mcp/providers",
        "/api/tools/personal-os/status",
        "/api/tools/personal-os/actions",
        "/api/tools/personal-os/audit",
        "/api/tools/cron/schedules",
        "/api/tools/cron/runs",
    ]:
        assert endpoint in text
    assert "method: 'POST'" not in text
    assert 'method: "POST"' not in text
    assert "method: 'DELETE'" not in text
    assert 'method: "DELETE"' not in text


def test_t9_tools_ops_tab_is_registered():
    text = Path("frontend/src/App.jsx").read_text(encoding="utf-8")
    assert "ToolsOpsCockpit" in text
    assert 'id: "tools_ops"' in text
    assert 'activeTab === "tools_ops"' in text