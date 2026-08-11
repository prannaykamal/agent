import re
from pathlib import Path

import pytest

from src.db import get_connection, init_db
from src.personal_os.tasks import create_task, list_tasks
from src.tools.policy import ToolCallerSource, ToolPolicyDecisionType, evaluate_tool_policy


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "tools_t10_personal_os.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file


def test_t10_personal_os_read_and_bounded_write_are_policy_known_and_audited(temp_db):
    read_decision = evaluate_tool_policy("list_tasks", {}, source=ToolCallerSource.CHAT)
    write_decision = evaluate_tool_policy("create_task", {"title": "T10"}, source=ToolCallerSource.CHAT)

    assert read_decision.decision == ToolPolicyDecisionType.NO_APPROVAL_NEEDED
    assert write_decision.decision in {
        ToolPolicyDecisionType.CONFIRMATION_RECOMMENDED,
        ToolPolicyDecisionType.APPROVAL_REQUIRED,
        ToolPolicyDecisionType.NO_APPROVAL_NEEDED,
    }

    result = create_task.invoke({"title": "T10 task", "description": "bounded local write", "priority": "Low"})
    assert "[Personal OS Task Created]" in result
    assert "T10 task" in list_tasks.invoke({})

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT tool_name, action FROM audit_logs ORDER BY created_at DESC LIMIT 1")
    row = dict(cursor.fetchone())
    conn.close()
    assert row["tool_name"] == "create_task"
    assert row["action"].startswith("PERSONAL_OS_")


def test_t10_synthetic_personal_os_tools_remain_blocked():
    for tool_name in ["sleep", "wake", "subscribe_event", "acquire_context", "release_context"]:
        decision = evaluate_tool_policy(tool_name, {}, source=ToolCallerSource.CHAT)
        assert decision.decision == ToolPolicyDecisionType.BLOCKED


def test_t10_personal_os_contains_no_provider_behavior_or_direct_memory_writes():
    combined = "\n".join(path.read_text(encoding="utf-8") for path in Path("src/personal_os").glob("*.py"))
    provider_terms = r"smtplib|imaplib|requests\.|TAVILY|WHATSAPP|TELEGRAM|GOOGLE_CALENDAR|duckduckgo|DDGS"
    assert re.search(provider_terms, combined, flags=re.IGNORECASE) is None

    direct_memory_terms = r"add_explicit_fact|StructuredEpisodeRepository|SkillVersionStore|pending_fact_candidates|semantic_embeddings|consolidation_runs"
    assert re.search(direct_memory_terms, combined) is None
