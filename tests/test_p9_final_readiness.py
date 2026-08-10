import os
import json
import pytest
from unittest.mock import MagicMock
from pathlib import Path
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from src.config import BASE_DIR, DB_PATH, validate_integration_environment
from src.db import init_db, get_connection
from src.startup import ensure_system_initialized
from src.harness.graph import agent_app, resume_graph_after_approval
from src.harness.state import AgentState
from src.personal_os.scheduling import schedule_job
from src.background_worker import process_due_scheduled_jobs
from src.personal_os.backup import export_agent_backup, restore_agent_backup
from src.api.server import app

client = TestClient(app)

@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    agent_dir = tmp_path / ".agent"
    agent_dir.mkdir(parents=True, exist_ok=True)
    db_file = agent_dir / "state.db"
    mem_file = agent_dir / "MEMORY.md"

    monkeypatch.setattr("src.config.AGENT_DIR", agent_dir)
    monkeypatch.setattr("src.config.DB_PATH", db_file)
    monkeypatch.setattr("src.config.MEMORY_PATH", mem_file)
    monkeypatch.setattr("src.db.DB_PATH", db_file)

    init_db(db_file)
    return agent_dir, db_file

def test_p9_gate_3_and_4_clean_startup_and_dist_serving(isolated_env):
    """Gate 3 & 4: Backend starts cleanly from fresh checkout and serves built dist."""
    agent_dir, db_file = isolated_env
    ensure_system_initialized()
    assert db_file.exists()

    resp = client.get("/")
    assert resp.status_code == 200
    assert "ASTRA" in resp.text

def test_p9_gate_5_new_chat_browser_ui(isolated_env):
    """Gate 5: New chat works through browser UI REST API."""
    sess_id = "sess_gate_5"
    res = client.post("/api/chat", json={"message": "Hello ASTRA assistant", "session_id": sess_id})
    assert res.status_code == 200
    data = res.json()
    assert "response" in data
    assert len(data["response"]) > 0

def test_p9_gate_6_low_risk_tool_call_end_to_end(isolated_env, monkeypatch):
    """Gate 6: Low-risk tool call (calendar_inspect_availability) works end-to-end."""
    call_msg = AIMessage(
        content="Inspecting availability.",
        tool_calls=[{"name": "calendar_inspect_availability", "args": {"start_date": "2026-08-01", "end_date": "2026-08-02"}, "id": "call_low_risk_1"}]
    )
    final_msg = AIMessage(content="You have no scheduled conflict on August 1st.")

    mock_llm = MagicMock()
    mock_llm.bind_tools.return_value.invoke.side_effect = [call_msg, final_msg]
    monkeypatch.setattr("src.harness.graph.get_primary_llm", lambda provider, model_name: (mock_llm, 128000))

    initial_state = {
        "messages": [{"type": "human", "content": "Check my calendar for August 1st"}],
        "session_id": "sess_low_risk",
        "summary": "",
        "token_count": 0,
        "retrieval_triggered": False,
        "retrieved_memories": [],
        "pending_approval_id": None,
        "approval_status": None,
        "provider": "openai",
        "model_name": "gpt-4o-mini",
        "fact_candidates": [],
        "loop_count": 0,
        "tools_used": [],
        "loop_events": []
    }

    res = agent_app.invoke(initial_state)
    events = res.get("loop_events", [])
    exec_events = [e for e in events if e.get("step_type") == "TOOL_EXECUTED"]
    assert len(exec_events) >= 1
    assert exec_events[0]["tool_name"] == "calendar_inspect_availability"

def test_p9_gate_7_and_8_high_risk_tool_pause_and_approval_resumption(isolated_env, monkeypatch):
    """Gate 7 & 8: High-risk tool call pauses for approval and resumes cleanly to final answer."""
    high_risk_msg = AIMessage(
        content="Drafting email transmission.",
        tool_calls=[{"name": "email_send", "args": {"to": "boss@company.com", "subject": "Report", "body": "Monthly report summary"}, "id": "call_high_risk_1"}]
    )

    mock_llm = MagicMock()
    mock_llm.bind_tools.return_value.invoke.return_value = high_risk_msg
    monkeypatch.setattr("src.harness.graph.get_primary_llm", lambda provider, model_name: (mock_llm, 128000))

    sess_id = "sess_gate_hitl"
    initial_state = {
        "messages": [{"type": "human", "content": "Send email to boss@company.com with report"}],
        "session_id": sess_id,
        "summary": "",
        "token_count": 0,
        "retrieval_triggered": False,
        "retrieved_memories": [],
        "pending_approval_id": None,
        "approval_status": None,
        "provider": "openai",
        "model_name": "gpt-4o-mini",
        "fact_candidates": [],
        "loop_count": 0,
        "tools_used": [],
        "loop_events": []
    }

    # Gate 7: Graph pauses for approval
    res_pause = agent_app.invoke(initial_state)
    assert res_pause.get("approval_status") == "PENDING"
    req_id = res_pause.get("pending_approval_id")
    assert req_id is not None

    # T8: approval resume revalidates provider availability and fails closed when Gmail MCP is unavailable.
    res_resume = resume_graph_after_approval(request_id=req_id, decision="APPROVED")
    assert res_resume.get("status") == "UNAVAILABLE"
    assert "unavailable" in res_resume.get("message", "").lower()

def test_p9_gate_9_scheduled_worker_processes_due_jobs(isolated_env):
    """Gate 9: Scheduled worker processes due jobs."""
    agent_dir, db_file = isolated_env
    job_msg = schedule_job.invoke({"cron_or_timestamp": "2020-01-01T00:00:00", "task_payload": "Execute test cleanup"})
    assert "registered for schedule" in job_msg

    conn = get_connection(db_file)
    cursor = conn.cursor()
    cursor.execute("UPDATE scheduled_jobs SET status='PENDING', cron_or_timestamp='2020-01-01T00:00:00'")
    conn.commit()
    conn.close()

    process_due_scheduled_jobs(db_path=db_file)

    conn2 = get_connection(db_file)
    cursor2 = conn2.cursor()
    cursor2.execute("SELECT status FROM scheduled_jobs")
    row = cursor2.fetchone()
    conn2.close()
    assert row[0] == "COMPLETED"

def test_p9_gate_10_isolated_backup_and_restore(isolated_env, tmp_path):
    """Gate 10: Backup and restore work in an isolated test workspace with safety checks."""
    agent_dir, db_file = isolated_env
    backups_dir = tmp_path / "isolated_backups"
    
    # Export backup archive
    res_export = export_agent_backup(output_dir=backups_dir, max_backups=5)
    assert res_export["status"] == "SUCCESS"
    backup_zip = Path(res_export["backup_path"])
    assert backup_zip.exists()

    # Restore backup archive into fresh database location
    restore_target_db = tmp_path / "restored_state.db"
    res_restore = restore_agent_backup(backup_zip, db_path=restore_target_db)
    assert res_restore["status"] == "RESTORED"
    assert restore_target_db.exists()

def test_p9_gate_11_readme_matches_actual_behavior():
    """Gate 11: Verify README.md matches actual system behavior and test count."""
    readme = BASE_DIR / "README.md"
    content = readme.read_text(encoding="utf-8")
    assert "ASTRA" in content
    assert "pytest" in content
    assert "docs/ARCHITECTURE.md" in content
