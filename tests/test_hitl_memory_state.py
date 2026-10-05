"""Jev memory routing survives the HITL pause -> decision -> resume lifecycle."""

import json
import sqlite3
from typing import Any, List, Optional

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from src.db import init_db
from src.harness.graph import agent_app, resume_graph_after_approval
from src.memory.cognee_memory import RETRIEVED_MEMORY_HEADER, get_cognee_memory

USER_TEXT = "Delegate the vendor plan review to a sub-agent"


class RecordingFakeLLM(BaseChatModel):
    responses: List[AIMessage]
    seen: List[List[Any]] = []

    def _generate(self, messages: List[Any], stop: Optional[List[str]] = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        self.seen.append(list(messages))
        resp = self.responses.pop(0) if self.responses else AIMessage(content="Delegation completed.")
        return ChatResult(generations=[ChatGeneration(message=resp)])

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        return self

    @property
    def _llm_type(self) -> str:
        return "recording_fake"


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "hitl_memory.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file


@pytest.fixture
def fake_llm(monkeypatch):
    llm = RecordingFakeLLM(
        responses=[
            AIMessage(
                content="",
                tool_calls=[{"name": "spawn_agent", "args": {"role": "Reviewer", "instructions": "Review vendor plan"}, "id": "call_spawn_1"}],
            ),
            AIMessage(content="The reviewer sub-agent is on it."),
        ],
        seen=[],
    )
    monkeypatch.setattr("src.harness.graph.get_primary_llm", lambda **kw: (llm, 128000))
    return llm


def _rows(db_path, sql, params=()):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def _session_writes(db_path, session_id):
    return _rows(db_path, "SELECT * FROM memory_jobs WHERE job_type = 'memory_session_write' AND session_id = ?", (session_id,))


def _pause(session_id):
    result = agent_app.invoke({"messages": [HumanMessage(content=USER_TEXT)], "session_id": session_id})
    assert result["approval_status"] == "PENDING"
    return result


# spawn_agent runs its own sub-agent turn (with its own Jev calls and recall), so
# only count activity for the original user turn.
def _jev_calls(fake_jev, kind):
    return [call for call in fake_jev.calls if call["kind"] == kind and USER_TEXT in call["user"]]


def _turn_searches(fake_cognee):
    return [call for call in fake_cognee.search_calls if call["query_text"] == USER_TEXT]


def test_pause_checkpoints_retrieval_routing_and_defers_storage(temp_db, fake_cognee, fake_jev, fake_llm):
    fake_jev.memory = {"should_store": True, "should_retrieve": False}

    paused = _pause("hitl-mem-pause")

    [approval] = _rows(temp_db, "SELECT checkpoint_id FROM approval_requests WHERE id = ?", (paused["pending_approval_id"],))
    [checkpoint] = _rows(temp_db, "SELECT state_json FROM checkpoints WHERE id = ?", (approval["checkpoint_id"],))
    memory_state = json.loads(checkpoint["state_json"])["memory_state"]
    assert memory_state["memory_retrieval_decision"]["should_retrieve"] is False
    assert "memory_storage_decision" not in memory_state
    # The paused turn has no final answer yet: no storage decision, no session write.
    assert len(_jev_calls(fake_jev, "retrieve")) == 1
    assert _jev_calls(fake_jev, "store") == []
    assert _session_writes(temp_db, "hitl-mem-pause") == []


def test_approved_resume_decides_storage_once_on_the_final_answer(temp_db, fake_cognee, fake_jev, fake_llm):
    fake_jev.memory = {"should_store": True, "should_retrieve": False}
    paused = _pause("hitl-mem-approve")

    resumed = resume_graph_after_approval(paused["pending_approval_id"], "APPROVED")

    assert resumed["status"] == "APPROVED"
    assert len(_jev_calls(fake_jev, "retrieve")) == 1
    [store_call] = _jev_calls(fake_jev, "store")
    assert "Assistant reply:" in store_call["user"]
    [job] = _session_writes(temp_db, "hitl-mem-approve")
    assert USER_TEXT in json.loads(job["payload_json"])["text"]
    [approval] = _rows(temp_db, "SELECT checkpoint_id FROM approval_requests WHERE id = ?", (paused["pending_approval_id"],))
    [checkpoint] = _rows(temp_db, "SELECT status FROM checkpoints WHERE id = ?", (approval["checkpoint_id"],))
    assert checkpoint["status"] == "RESTORED"


def test_approved_resume_respects_should_store_false(temp_db, fake_cognee, fake_jev, fake_llm):
    fake_jev.memory = {"should_store": False, "should_retrieve": False}
    paused = _pause("hitl-mem-nostore")

    resume_graph_after_approval(paused["pending_approval_id"], "APPROVED")

    assert _session_writes(temp_db, "hitl-mem-nostore") == []
    assert len(_jev_calls(fake_jev, "store")) == 1


def test_rejected_resume_is_never_stored_and_does_not_call_jev(temp_db, fake_cognee, fake_jev, fake_llm):
    fake_jev.memory = {"should_store": True, "should_retrieve": False}
    paused = _pause("hitl-mem-reject")

    resumed = resume_graph_after_approval(paused["pending_approval_id"], "REJECTED")

    assert resumed["status"] == "REJECTED"
    assert _session_writes(temp_db, "hitl-mem-reject") == []
    assert len(_jev_calls(fake_jev, "retrieve")) == 1
    assert _jev_calls(fake_jev, "store") == []


def test_resume_reinjects_recalled_memory_without_searching_again(temp_db, fake_cognee, fake_jev, fake_llm):
    get_cognee_memory().remember_permanent(["The vendor plan reviewer should always be Priya."])
    fake_jev.memory = {"should_store": False, "should_retrieve": True}
    paused = _pause("hitl-mem-recall")
    assert paused["retrieval_triggered"] is True
    assert len(_turn_searches(fake_cognee)) == 1

    resume_graph_after_approval(paused["pending_approval_id"], "APPROVED")

    assert len(_turn_searches(fake_cognee)) == 1
    assert len(_jev_calls(fake_jev, "retrieve")) == 1
    resumed_prompt = [
        prompt for prompt in fake_llm.seen
        if any(isinstance(m, HumanMessage) and m.content == USER_TEXT for m in prompt)
    ][-1]
    blocks = [m for m in resumed_prompt if isinstance(m, SystemMessage) and RETRIEVED_MEMORY_HEADER in str(m.content)]
    assert blocks and "Priya" in str(blocks[0].content)


def test_resume_from_checkpoint_without_memory_state_still_works(temp_db, fake_cognee, fake_jev, fake_llm):
    fake_jev.memory = {"should_store": True, "should_retrieve": False}
    paused = _pause("hitl-mem-old")
    [approval] = _rows(temp_db, "SELECT checkpoint_id FROM approval_requests WHERE id = ?", (paused["pending_approval_id"],))
    conn = sqlite3.connect(temp_db)
    try:
        conn.execute("UPDATE checkpoints SET state_json = ? WHERE id = ?", (json.dumps({"task_id": "hitl-mem-old"}), approval["checkpoint_id"]))
        conn.commit()
    finally:
        conn.close()

    resumed = resume_graph_after_approval(paused["pending_approval_id"], "APPROVED")

    assert resumed["status"] == "APPROVED"
    assert len(_jev_calls(fake_jev, "retrieve")) == 1
    assert len(_session_writes(temp_db, "hitl-mem-old")) == 1


def test_chat_yes_approval_stores_the_original_request_not_the_reply(temp_db, fake_cognee, fake_jev, fake_llm):
    from fastapi.testclient import TestClient
    from src.api.server import app

    fake_jev.memory = {"should_store": True, "should_retrieve": False}
    _pause("hitl-mem-chat-yes")

    response = TestClient(app).post("/api/chat", json={"message": "yes", "session_id": "hitl-mem-chat-yes"})

    assert response.status_code == 200
    assert response.json()["approval_status"] == "APPROVED"
    [store_call] = _jev_calls(fake_jev, "store")
    assert store_call["user"].startswith(f"User message: {USER_TEXT}")
    [job] = _session_writes(temp_db, "hitl-mem-chat-yes")
    # The fake Jev distills the request it was shown; it must be the original one, not "yes".
    assert json.loads(job["payload_json"])["text"] == USER_TEXT


def test_resume_keeps_the_turns_provider_and_model(temp_db, fake_cognee, fake_jev, monkeypatch):
    llm = RecordingFakeLLM(
        responses=[
            AIMessage(content="", tool_calls=[{"name": "spawn_agent", "args": {"role": "Reviewer", "instructions": "Review"}, "id": "call_spawn_2"}]),
            AIMessage(content="Done."),
        ],
        seen=[],
    )
    selections = []

    def fake_get_primary_llm(**kwargs):
        selections.append((kwargs.get("provider"), kwargs.get("model_name")))
        return llm, 128000

    monkeypatch.setattr("src.harness.graph.get_primary_llm", fake_get_primary_llm)
    paused = agent_app.invoke({
        "messages": [HumanMessage(content=USER_TEXT)],
        "session_id": "hitl-mem-model",
        "provider": "anthropic",
        "model_name": "claude-test-model",
    })
    assert paused["approval_status"] == "PENDING"
    selections.clear()

    resume_graph_after_approval(paused["pending_approval_id"], "APPROVED")

    # The sub-agent spawned by the tool uses its own defaults; the resumed turn keeps the user's choice.
    assert ("anthropic", "claude-test-model") in selections
