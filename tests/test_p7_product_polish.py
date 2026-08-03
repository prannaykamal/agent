import pytest
from fastapi.testclient import TestClient
from src.api.server import app

client = TestClient(app)

def test_p7_1_system_health_endpoint():
    """P7 Items 5 & 6: Verifies GET /api/system/health returns runtime telemetry and provider flags."""
    res = client.get("/api/system/health")
    assert res.status_code == 200
    data = res.json()

    assert data["status"] == "HEALTHY"
    assert "ASTRA" in data["app_name"]
    assert "database_path" in data
    assert "schema_version" in data
    assert data["worker_status"] == "RUNNING"
    assert isinstance(data["providers"], dict)

def test_p7_2_product_branding_title_standardization():
    """P7 Item 2: Verifies standardized ASTRA product title in system health endpoint."""
    res = client.get("/api/system/health")
    assert res.status_code == 200
    data = res.json()
    assert data["app_name"] == "ASTRA (Autonomous System for Tasks, Reasoning & Assistance)"

def test_p7_3_session_rename_and_delete_endpoints():
    """P7 Item 9: Verifies session rename and delete REST contracts."""
    sess_id = "sess_p7_test"
    renamed_id = "sess_p7_renamed"

    # Post chat message to populate session
    r_chat = client.post("/api/chat", json={"message": "Ping", "session_id": sess_id})
    assert r_chat.status_code == 200

    # Rename session
    r_rename = client.put(f"/api/history/{sess_id}", json={"new_session_id": renamed_id})
    assert r_rename.status_code == 200
    assert r_rename.json()["status"].lower() == "success"

    # Delete session
    r_del = client.delete(f"/api/history/{renamed_id}")
    assert r_del.status_code == 200
    assert r_del.json()["status"].lower() == "success"

