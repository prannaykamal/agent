from fastapi.testclient import TestClient

from src.api.server import app
from src.db import init_db
from src.hitl.approval_engine import create_approval_request


def test_t8_api_tools_shape_stays_compatible_and_excludes_unavailable_mcp(tmp_path, monkeypatch):
    monkeypatch.setattr("src.mcp_gateway.registry.load_live_mcp_tools", lambda: [])
    db_file = tmp_path / "api_tools.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    client = TestClient(app)
    response = client.get("/api/tools")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"total_tools", "personal_os_tools", "mcp_tools"}
    assert any(tool["name"] == "heartbeat" for tool in body["personal_os_tools"])
    assert all(tool["name"] != "email_send" for tool in body["mcp_tools"])


def test_t8_api_approval_decision_revalidates_policy_before_execution(tmp_path, monkeypatch):
    monkeypatch.setattr("src.mcp_gateway.registry.load_live_mcp_tools", lambda: [])
    db_file = tmp_path / "api_approval.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    req = create_approval_request("sess", "email_send", {"recipient": "a@example.com"}, "send", db_path=db_file)
    client = TestClient(app)
    response = client.post(f"/api/approvals/{req['request_id']}/decision", json={"decision": "APPROVED"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "UNAVAILABLE"
    assert "unavailable" in body["message"].lower()