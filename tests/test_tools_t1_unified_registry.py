import pytest

from src.tools.registry_types import (
    ApprovalPolicy,
    ImplementationType,
    RiskClass,
)


@pytest.fixture(autouse=True)
def disable_live_mcp_discovery(monkeypatch):
    monkeypatch.setattr("src.mcp_gateway.registry.load_live_mcp_tools", lambda: [])


def test_t1_personal_os_tools_have_local_metadata():
    from src.tools.registry import get_personal_os_tool_metadata

    metadata = get_personal_os_tool_metadata()
    by_name = {item.legacy_name: item for item in metadata}

    assert by_name["create_task"].implementation_type == ImplementationType.LOCAL
    assert by_name["create_task"].provider == "personal_os"
    assert by_name["heartbeat"].category == "health"
    assert by_name["schedule_job"].risk_class == RiskClass.MEDIUM


def test_t1_mcp_gateway_tools_have_transitional_mcp_metadata():
    from src.tools.registry import get_mcp_gateway_tool_metadata

    metadata = get_mcp_gateway_tool_metadata()
    by_name = {item.legacy_name: item for item in metadata}

    assert by_name["search_web"].implementation_type == ImplementationType.MCP
    assert by_name["search_web"].provider == "mcp_gateway"
    assert by_name["search_web"].provider_managed is False
    assert by_name["search_web"].observability_metadata["legacy_local_adapter_backed"] is True
    assert by_name["email_send"].approval_policy == ApprovalPolicy.APPROVAL_REQUIRED


def test_t1_removed_target_metadata_exists_for_browser_and_code_sandbox_tools():
    from src.tools.registry import get_removed_tool_metadata

    removed = get_removed_tool_metadata()
    by_name = {item.legacy_name: item for item in removed}

    expected = {
        "safe_browse_url",
        "capture_screenshot",
        "run_code",
        "github_clone",
        "github_commit_and_push",
        "github_merge",
    }
    assert expected <= set(by_name)
    for name in expected:
        assert by_name[name].implementation_type == ImplementationType.REMOVED
        assert by_name[name].enabled is False
        assert by_name[name].removal_reason


def test_t1_every_unified_metadata_entry_has_stable_required_fields():
    from src.tools.registry import get_unified_tool_metadata

    metadata = get_unified_tool_metadata()
    tool_ids = [item.tool_id for item in metadata]

    assert len(tool_ids) == len(set(tool_ids))
    assert metadata
    for item in metadata:
        assert item.tool_id
        assert item.legacy_name
        assert item.provider
        assert item.category
        assert item.risk_class
        assert item.approval_policy
        assert item.implementation_type in {
            ImplementationType.LOCAL,
            ImplementationType.MCP,
            ImplementationType.REMOVED,
        }


def test_t1_bindable_metadata_preserves_current_active_sandbox_baseline():
    from src.tools.registry import get_bindable_tool_metadata

    by_name = {item.legacy_name: item for item in get_bindable_tool_metadata()}

    # T1 metadata only: sandbox tools are still active until T2/T3.
    assert by_name["safe_browse_url"].implementation_type == ImplementationType.MCP
    assert by_name["capture_screenshot"].implementation_type == ImplementationType.MCP
    assert by_name["run_code"].implementation_type == ImplementationType.MCP
    assert by_name["github_merge"].implementation_type == ImplementationType.MCP


def test_t1_metadata_lookup_helpers_return_active_metadata_before_removed_target_metadata():
    from src.tools.registry import (
        get_tool_metadata_by_id,
        get_tool_metadata_by_legacy_name,
        get_unified_tool_metadata_by_id,
    )

    active_run_code = get_tool_metadata_by_legacy_name("run_code")
    removed_run_code = get_tool_metadata_by_id("removed.code.run_code")
    by_id = get_unified_tool_metadata_by_id()

    assert active_run_code is not None
    assert active_run_code.implementation_type == ImplementationType.MCP
    assert removed_run_code is not None
    assert removed_run_code.implementation_type == ImplementationType.REMOVED
    assert by_id[removed_run_code.tool_id] == removed_run_code
