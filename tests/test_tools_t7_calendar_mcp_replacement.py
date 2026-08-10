from src.mcp_gateway.calendar import (
    calendar_create_event,
    calendar_delete_event,
    calendar_inspect_availability,
    calendar_update_event,
    detect_calendar_conflicts,
)
from src.mcp_gateway.registry import get_mcp_tool_risk
from src.tools.mcp_invocation import MCPInvocationResult, MCPInvocationStatus


def test_t7_calendar_read_and_writes_use_mcp_boundary(monkeypatch):
    calls = []

    def fake_invoke(provider_ids, tool_hints, arguments, **_kwargs):
        calls.append((provider_ids, tool_hints, arguments))
        return MCPInvocationResult(status=MCPInvocationStatus.SUCCEEDED, provider_id="google_calendar", tool_name="calendar_tool", content="calendar ok")

    monkeypatch.setattr("src.tools.mcp_invocation.invoke_provider_tool", fake_invoke)

    assert calendar_inspect_availability.invoke({"start_date": "2026-08-01", "end_date": "2026-08-02"}) == "calendar ok"
    assert calendar_create_event.invoke({"title": "Sync", "start_time": "10:00", "end_time": "11:00"}) == "calendar ok"
    assert calendar_update_event.invoke({"event_id": "evt_1", "title": "Sync", "start_time": "10:00", "end_time": "11:00"}) == "calendar ok"
    assert calendar_delete_event.invoke({"event_id": "evt_1"}) == "calendar ok"

    assert all(call[0] == ("google_calendar",) for call in calls)
    assert any("create" in call[1] for call in calls)
    assert any("delete" in call[1] for call in calls)


def test_t7_calendar_local_conflict_detection_is_not_source_of_truth():
    assert detect_calendar_conflicts("10:00", "11:00") == []


def test_t7_calendar_unavailable_is_safe(monkeypatch):
    monkeypatch.setattr(
        "src.tools.mcp_invocation.invoke_provider_tool",
        lambda *args, **_kwargs: MCPInvocationResult(status=MCPInvocationStatus.PROVIDER_UNAVAILABLE),
    )

    result = calendar_create_event.invoke({"title": "Sync", "start_time": "10:00", "end_time": "11:00"})
    assert "Unavailable" in result


def test_t7_calendar_write_policy_metadata_is_preserved():
    assert get_mcp_tool_risk("calendar_create_event") == "High"
    assert get_mcp_tool_risk("calendar_update_event") == "High"
    assert get_mcp_tool_risk("calendar_delete_event") == "High"
