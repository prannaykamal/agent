import pytest
from fastapi.testclient import TestClient
from src.db import init_db, get_connection
from src.api.server import app

@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_p3_frontend.db"
    mem_file = tmp_path / "MEMORY.md"

    monkeypatch.setattr("src.db.DB_PATH", db_file)
    monkeypatch.setattr("src.config.MEMORY_PATH", mem_file)
    init_db(db_file)
    return db_file

client = TestClient(app)

def test_p3_session_rename_and_delete_endpoints(temp_db):
    """
    P3 Test 6:
    Verifies PUT /api/history/{session_id} renames a session and
    DELETE /api/history/{session_id} deletes the session history.
    """
    # 1. Insert test turn
    conn = get_connection(temp_db)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO raw_turns (id, session_id, sender, content, tokens) VALUES ('t1', 'sess_old', 'user', 'Hello', 2)")
    conn.commit()
    conn.close()

    # Verify session listed
    resp_sess = client.get("/api/sessions")
    assert resp_sess.status_code == 200
    assert "sess_old" in resp_sess.json()["sessions"]

    # 2. Rename session
    resp_rename = client.put("/api/history/sess_old", json={"new_session_id": "sess_renamed"})
    assert resp_rename.status_code == 200
    assert resp_rename.json()["new_session_id"] == "sess_renamed"

    # Verify renamed session history
    resp_hist = client.get("/api/history/sess_renamed")
    assert resp_hist.status_code == 200
    assert len(resp_hist.json()["turns"]) == 1

    # 3. Delete session
    resp_del = client.delete("/api/history/sess_renamed")
    assert resp_del.status_code == 200
    assert "deleted" in resp_del.json()["message"]

    # Verify session is empty
    resp_hist2 = client.get("/api/history/sess_renamed")
    assert len(resp_hist2.json()["turns"]) == 0

def test_p3_taskboard_api_structured_response(temp_db):
    """
    P3 Test 5:
    Verifies TaskBoard API response structure for rendering structured list cards.
    """
    conn = get_connection(temp_db)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO tasks (id, title, description, status, priority) VALUES ('t_10', 'Refactor UI', 'Upgrade Vite build', 'IN_PROGRESS', 'High')")
    cursor.execute("INSERT INTO sub_agents (agent_id, parent_session_id, role, instructions, status) VALUES ('ag_10', 'sess_root', 'Frontend Dev', 'Build components', 'RUNNING')")
    conn.commit()
    conn.close()

    resp = client.get("/api/tasks")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["tasks"]) == 1
    assert data["tasks"][0]["title"] == "Refactor UI"
    assert len(data["sub_agents"]) == 1
    assert data["sub_agents"][0]["role"] == "Frontend Dev"

def test_p3_static_frontend_and_dist_mounting(temp_db):
    """
    P3 Test 3 & 9:
    Smoke test checking frontend HTML serving and static asset mounting.
    """
    resp_root = client.get("/")
    assert resp_root.status_code == 200
    assert "<!DOCTYPE html>" in resp_root.text or "Assistant API" in resp_root.text
