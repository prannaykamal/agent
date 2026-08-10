import json

import pytest

from src.db import get_connection, init_db
from src.personal_os.audit import redact_personal_os_value
from src.personal_os.idempotency import make_personal_os_idempotency_key
from src.personal_os.tasks import create_task


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_tools_t4_personal_os_audit.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file


def test_t4_idempotency_key_is_stable_for_normalized_payload():
    key1 = make_personal_os_idempotency_key(
        tool_name="create_task",
        session_id="s1",
        target_resource="task_x",
        payload={"title": "A", "priority": "High"},
    )
    key2 = make_personal_os_idempotency_key(
        tool_name="create_task",
        session_id="s1",
        target_resource="task_x",
        payload={"priority": "High", "title": "A"},
    )
    assert key1 == key2
    assert key1.startswith("pos_")


def test_t4_redaction_removes_secrets_and_truncates_raw_fields():
    redacted = redact_personal_os_value({
        "api_token": "secret-token",
        "chain_of_thought": "hidden",
        "payload": "x" * 300,
        "safe": "ok",
    })
    assert redacted["api_token"] == "[REDACTED]"
    assert redacted["chain_of_thought"] == "[REDACTED]"
    assert redacted["safe"] == "ok"
    assert len(redacted["payload"]) < 170


def test_t4_write_action_creates_redacted_audit_record(temp_db):
    result = create_task.invoke({"title": "Audit task", "description": "secret-ish details", "priority": "Low"})
    assert "[Personal OS Task Created]" in result

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT tool_name, tool_args_json, risk_level, action, details FROM audit_logs ORDER BY created_at DESC LIMIT 1")
    row = dict(cursor.fetchone())
    conn.close()

    assert row["tool_name"] == "create_task"
    assert row["risk_level"] == "Medium"
    assert row["action"] == "PERSONAL_OS_TASK_CREATED"
    assert "idempotency_key=pos_" in row["details"]
    args = json.loads(row["tool_args_json"])
    assert args["title"] == "Audit task"
