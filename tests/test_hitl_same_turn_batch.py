import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.db import init_db
from src.harness.graph import node_hitl_check, resume_graph_after_approval
from src.hitl.approval_engine import generate_payload_preview, get_approval_request
from src.tools.invocation import ToolInvocationResult
from src.tools.policy import RiskClass, ToolPolicyDecision, ToolPolicyDecisionType


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_hitl_same_turn_batch.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file


def _five_email_calls():
    return [
        {
            "name": "email_send",
            "args": {
                "recipient": "friend@example.com",
                "subject": "Happy Independence Day",
                "body": "Wishing you a happy 15 August!",
            },
            "id": f"call_send_{index}",
        }
        for index in range(1, 6)
    ]


def test_payload_preview_mentions_same_turn_batch():
    preview = generate_payload_preview(
        "email_send",
        {
            "recipient": "friend@example.com",
            "subject": "Happy Independence Day",
            "body": "Wishing you a happy 15 August!",
            "_batch_calls": [{"name": "email_send"}] * 5,
        },
    )
    assert "[Batch of 5 'email_send' actions]" in preview
    assert "friend@example.com" in preview
    assert "_batch_calls" not in preview


def test_hitl_pause_stores_same_turn_high_risk_batch(temp_db):
    result = node_hitl_check(
        {
            "messages": [
                HumanMessage(content="send him this 5 times"),
                AIMessage(content="Sending five emails.", tool_calls=_five_email_calls()),
            ],
            "session_id": "sess_batch_pause",
            "loop_events": [],
        }
    )
    assert result["approval_status"] == "PENDING"
    pause_text = result["messages"][-1].content
    assert "This approval covers 5 'email_send' actions from this turn." in pause_text

    stored = get_approval_request(result["pending_approval_id"], db_path=temp_db)
    batch = (stored.get("tool_args") or {}).get("_batch_calls") or []
    assert len(batch) == 5
    assert [item["id"] for item in batch] == [f"call_send_{index}" for index in range(1, 6)]


def test_approval_resume_executes_every_same_turn_sibling(temp_db, monkeypatch):
    invocations = []

    def fake_invoke(tool_name, arguments, tool_map, *, source="chat", approval_context=None):
        invocations.append({"name": tool_name, "args": dict(arguments or {})})
        return ToolInvocationResult(
            tool_name=tool_name,
            status="SUCCEEDED",
            output=f"sent:{arguments.get('recipient')}:{len(invocations)}",
            policy_decision=ToolPolicyDecision(
                tool_name=tool_name,
                decision=ToolPolicyDecisionType.NO_APPROVAL_NEEDED,
                risk_class=RiskClass.HIGH,
            ),
        )

    monkeypatch.setattr("src.harness.graph.invoke_registered_tool", fake_invoke)
    monkeypatch.setattr(
        "src.harness.graph.evaluate_tool_policy",
        lambda *args, **kwargs: ToolPolicyDecision(
            tool_name="email_send",
            decision=ToolPolicyDecisionType.NO_APPROVAL_NEEDED,
            risk_class=RiskClass.HIGH,
        ),
    )
    monkeypatch.setattr(
        "src.harness.graph.agent_app.invoke",
        lambda state: {"messages": [AIMessage(content="Sent all five emails.")]},
    )

    pause = node_hitl_check(
        {
            "messages": [
                HumanMessage(content="send him this 5 times"),
                AIMessage(content="Sending five emails.", tool_calls=_five_email_calls()),
            ],
            "session_id": "sess_batch_resume",
            "loop_events": [],
        }
    )
    resume = resume_graph_after_approval(pause["pending_approval_id"], "APPROVED")
    assert resume["status"] == "APPROVED"
    assert len(invocations) == 5
    assert all(item["name"] == "email_send" for item in invocations)
    assert "[1/5]" in resume["tool_result"]
    assert "[5/5]" in resume["tool_result"]
