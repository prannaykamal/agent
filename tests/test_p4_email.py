import pytest
from fastapi.testclient import TestClient
from src.db import init_db
from src.mcp_gateway.communication import email_read, email_search, email_draft, email_send
from src.api.server import app


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_p4_email.db"
    mem_file = tmp_path / "MEMORY.md"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    monkeypatch.setattr("src.config.MEMORY_PATH", mem_file)
    init_db(db_file)
    return db_file


client = TestClient(app)


def test_email_tools_use_gmail_mcp_unavailable_state(temp_db, monkeypatch):
    from src.tools.mcp_invocation import MCPInvocationResult, MCPInvocationStatus

    monkeypatch.setattr(
        "src.tools.mcp_invocation.invoke_provider_tool",
        lambda *args, **kwargs: MCPInvocationResult(status=MCPInvocationStatus.PROVIDER_UNAVAILABLE),
    )

    assert "Unavailable" in email_draft.invoke({"to": "client@example.com", "subject": "Project", "body": "Body"})
    assert "Unavailable" in email_read.invoke({"limit": 5})
    assert "Unavailable" in email_search.invoke({"query": "Proposal"})
    assert "Unavailable" in email_send.invoke({"to": "client@example.com", "subject": "Final", "body": "Body"})


def test_email_rest_api_endpoints_keep_shape(temp_db):
    resp_draft = client.post("/api/email/draft", json={"to": "boss@company.com", "subject": "Weekly Update", "body": "All tests passing."})
    assert resp_draft.status_code == 200
    assert "result" in resp_draft.json()

    resp_get = client.get("/api/email/messages")
    assert resp_get.status_code == 200
    assert resp_get.json()["messages"] == []
    assert "result" in resp_get.json()

    resp_send = client.post("/api/email/send", json={"to": "boss@company.com", "subject": "Urgent", "body": "Report"})
    assert resp_send.status_code == 200
    assert resp_send.json()["status"] == "APPROVAL_REQUIRED"
