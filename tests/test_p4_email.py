import pytest
from fastapi.testclient import TestClient
from src.db import init_db, get_connection
from src.mcp_gateway.communication import email_read, email_search, email_draft, email_send
from src.mcp_gateway.email_adapters import SMTPEmailAdapter, IMAPEmailAdapter
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

def test_email_tools_and_sqlite_storage(temp_db):
    """Verifies local-first SQLite email tools: draft, read, search, send."""
    # 1. Save draft
    res_draft = email_draft.invoke({"to": "client@example.com", "subject": "Project Proposal", "body": "Please find proposal attached."})
    assert "Draft Saved" in res_draft

    # 2. Read inbox/drafts
    res_read = email_read.invoke({"limit": 5})
    assert "Project Proposal" in res_read

    # 3. Search emails
    res_search = email_search.invoke({"query": "Proposal"})
    assert "Project Proposal" in res_search

    # 4. Send email
    res_send = email_send.invoke({"to": "client@example.com", "subject": "Final Invoice", "body": "Invoice for Q3 services."})
    assert "SENT" in res_send

def test_email_adapters_local_mode(temp_db):
    """Verifies SMTPEmailAdapter and IMAPEmailAdapter operate gracefully in local-first mode."""
    smtp_adapter = SMTPEmailAdapter()
    res_send = smtp_adapter.send_email(to_addr="test@example.com", subject="Test SMTP", body="Hello")
    assert res_send["status"] == "sent"
    assert res_send["mode"] == "LOCAL_SQLITE"

    imap_adapter = IMAPEmailAdapter()
    res_fetch = imap_adapter.fetch_recent_emails(limit=5)
    assert isinstance(res_fetch, list)

def test_email_rest_api_endpoints(temp_db):
    """Verifies REST API endpoints GET /api/email/messages, POST /api/email/draft, POST /api/email/send."""
    # POST draft
    resp_draft = client.post("/api/email/draft", json={
        "to": "boss@company.com",
        "subject": "Weekly Update",
        "body": "All 104 tests passing."
    })
    assert resp_draft.status_code == 200
    assert "Draft Saved" in resp_draft.json()["result"]

    # GET messages
    resp_get = client.get("/api/email/messages")
    assert resp_get.status_code == 200
    messages = resp_get.json()["messages"]
    assert len(messages) >= 1
    assert messages[0]["subject"] == "Weekly Update"

    # POST send
    resp_send = client.post("/api/email/send", json={
        "to": "boss@company.com",
        "subject": "Urgent Report",
        "body": "Report content here."
    })
    assert resp_send.status_code == 200
    assert resp_send.json()["status"] == "APPROVAL_REQUIRED"

