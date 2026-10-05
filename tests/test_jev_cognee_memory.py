"""Jev routing + cognee session memory: storage, idle merge, retrieval, tool review, failures."""

import json
import sqlite3
from datetime import datetime, timedelta, timezone

from contextlib import contextmanager

import pytest
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, SystemMessage

from src.db import init_db
from src.harness.graph import build_agent_graph, node_consolidate, node_memory_router, node_tools
from src.memory.cognee_memory import RETRIEVED_MEMORY_HEADER, get_cognee_memory, session_key
from src.memory.config import JevConfig
from src.memory.jev import JevClient, get_jev_client, set_jev_client
from src.memory.worker import process_one_memory_job

# Jobs are enqueued with SQLite's real datetime('now'), and the worker only claims
# jobs whose available_at <= its clock. Anchor the test clock a day ahead of real
# time so every enqueued job is claimable regardless of when the suite runs.
NOW = (datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=1)).replace(minute=0, second=0, microsecond=0)


def _sql_ts(value):
    return value.strftime("%Y-%m-%d %H:%M:%S")


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "jev_cognee.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file


@pytest.fixture
def clock(monkeypatch):
    """Controls the handlers' notion of now."""
    state = {"now": NOW}
    monkeypatch.setattr("src.memory.job_handlers._utcnow", lambda: state["now"])
    return state


def _rows(db_path, sql, params=()):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def _jobs(db_path, job_type):
    return _rows(db_path, "SELECT * FROM memory_jobs WHERE job_type = ? ORDER BY created_at, rowid", (job_type,))


def _turn(db_path, session_id, at, sender="user", content="hi"):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO raw_turns (id, session_id, sender, content, tokens, created_at) VALUES (?, ?, ?, ?, 1, ?)",
            (f"t-{session_id}-{at.timestamp()}-{sender}", session_id, sender, content, at.strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.commit()
    finally:
        conn.close()


def _completed_state(session_id, user_text, assistant_text, *, tools_used=()):
    return {
        "messages": [HumanMessage(content=user_text), AIMessage(content=assistant_text)],
        "session_id": session_id,
        "approval_status": "NONE",
        "provider": "openai",
        "model_name": "gpt-4o-mini",
        "tools_used": list(tools_used),
        "loop_count": 1,
    }


def _work(db_path, clock, steps=5):
    """Run the worker until idle, at the clock's current time."""
    results = []
    for _ in range(steps):
        result = process_one_memory_job("test-worker", db_path=db_path, now=clock["now"])
        if result.job_id is None:
            break
        results.append(result)
    return results


@contextmanager
def _jev_storing(memory):
    """Jev answers should_store=true with ``memory`` as the distilled text, whatever the test's Jev is."""
    previous = get_jev_client()
    answer = json.dumps({"should_store": True, "memory": memory})
    set_jev_client(JevClient(config=JevConfig(endpoint="http://jev.test/v1", model="jev-test"), completion_fn=lambda messages: answer))
    try:
        yield
    finally:
        set_jev_client(previous)


def _store_turn(db_path, clock, session_id, user_text, assistant_text="Noted."):
    """Store a turn whose distilled memory is the user's own statement."""
    _turn(db_path, session_id, clock["now"], "user", user_text)
    with _jev_storing(user_text):
        node_consolidate(_completed_state(session_id, user_text, assistant_text))
    return _work(db_path, clock)


def _route(text, session_id="s1", messages=None):
    return node_memory_router({"messages": messages or [HumanMessage(content=text)], "session_id": session_id})


def _conversation(messages):
    """Messages as the graph will hold them, minus LangGraph's replace-all marker."""
    return [m for m in messages if not isinstance(m, RemoveMessage)]


def _memory_blocks(messages):
    return [m for m in messages if isinstance(m, SystemMessage) and str(m.content).startswith(RETRIEVED_MEMORY_HEADER)]


# --- Storage -----------------------------------------------------------------


def test_should_store_false_adds_nothing_to_session_memory(temp_db, fake_cognee, fake_jev, clock):
    fake_jev.memory = {"should_store": False, "should_retrieve": False}

    result = node_consolidate(_completed_state("s1", "What is the capital of France?", "Paris."))

    assert result["memory_storage_decision"]["should_store"] is False
    assert result["memory_job_ids"] == []
    assert _jobs(temp_db, "memory_session_write") == []
    assert fake_cognee.sessions == {}


def test_should_store_true_writes_turn_to_the_session_graph(temp_db, fake_cognee, fake_jev, clock):
    fake_jev.memory = {"should_store": True, "should_retrieve": False}

    steps = _store_turn(temp_db, clock, "s1", "Remember that I prefer short responses.", "Got it, short responses.")

    key = session_key("default_user", "s1")
    assert [step.job_type for step in steps] == ["memory_session_write"]
    # Only the distilled memory is written, never the "User: ... Assistant: ..." transcript.
    assert fake_cognee.sessions[key] == ["Remember that I prefer short responses."]
    assert fake_cognee.remember_calls[-1] == {"dataset_name": "ivo_memory", "session_id": key, "self_improvement": False}
    # Nothing reaches the main graph until the session is idle.
    assert fake_cognee.graph == {}
    [merge] = _jobs(temp_db, "memory_session_merge")
    assert merge["status"] == "QUEUED"
    assert merge["available_at"] == _sql_ts(NOW + timedelta(minutes=30))


def test_multiple_queries_share_one_session_graph(temp_db, fake_cognee, clock):
    _store_turn(temp_db, clock, "s1", "My manager is Priya.")
    clock["now"] += timedelta(minutes=2)
    _store_turn(temp_db, clock, "s1", "I work on the Atlas migration.")

    assert list(fake_cognee.sessions) == [session_key("default_user", "s1")]
    assert len(fake_cognee.sessions[session_key("default_user", "s1")]) == 2


def test_idle_session_merges_into_main_graph_once(temp_db, fake_cognee, clock):
    _store_turn(temp_db, clock, "s1", "My manager is Priya.")

    clock["now"] += timedelta(minutes=31)
    steps = _work(temp_db, clock)

    assert [step.job_type for step in steps] == ["memory_session_merge"]
    assert fake_cognee.improve_calls == [{"dataset": "ivo_memory", "session_ids": [session_key("default_user", "s1")]}]
    assert any("Priya" in text for text in fake_cognee.graph["ivo_memory"])
    result = json.loads(_jobs(temp_db, "memory_session_merge")[0]["result_json"])
    assert result["merged"] is True and result["merged_write_count"] == 1


def test_active_conversation_defers_the_merge(temp_db, fake_cognee, clock):
    _store_turn(temp_db, clock, "s1", "My manager is Priya.")
    # The user keeps talking (a turn not worth storing) 20 minutes later.
    _turn(temp_db, "s1", NOW + timedelta(minutes=20))

    clock["now"] = NOW + timedelta(minutes=31)
    _work(temp_db, clock)

    assert fake_cognee.improve_calls == []
    merges = _jobs(temp_db, "memory_session_merge")
    assert json.loads(merges[0]["result_json"])["deferred"] is True
    assert merges[-1]["status"] == "QUEUED" and merges[-1]["available_at"] == _sql_ts(NOW + timedelta(minutes=50))

    clock["now"] = NOW + timedelta(minutes=51)
    _work(temp_db, clock)
    assert len(fake_cognee.improve_calls) == 1


def test_duplicate_idle_events_do_not_merge_twice(temp_db, fake_cognee, clock):
    from src.memory.jobs import SQLiteMemoryJobQueue, build_memory_session_merge_job_spec

    _store_turn(temp_db, clock, "s1", "My manager is Priya.")
    due = NOW + timedelta(minutes=30)
    duplicate = SQLiteMemoryJobQueue().enqueue_spec(build_memory_session_merge_job_spec(user_id="default_user", session_id="s1", run_at=due))
    late = SQLiteMemoryJobQueue().enqueue_spec(
        build_memory_session_merge_job_spec(user_id="default_user", session_id="s1", run_at=due + timedelta(minutes=5))
    )

    clock["now"] = NOW + timedelta(minutes=40)
    _work(temp_db, clock)

    assert duplicate.inserted is False
    assert late.inserted is True
    assert len(fake_cognee.improve_calls) == 1
    results = [json.loads(job["result_json"]) for job in _jobs(temp_db, "memory_session_merge")]
    assert sorted(r.get("skipped", "merged") for r in results) == ["merged", "nothing_to_merge"]


def test_new_query_after_idle_continues_the_session_and_merges_again(temp_db, fake_cognee, clock):
    _store_turn(temp_db, clock, "s1", "My manager is Priya.")
    clock["now"] = NOW + timedelta(minutes=31)
    _work(temp_db, clock)

    clock["now"] = NOW + timedelta(hours=2)
    _store_turn(temp_db, clock, "s1", "Priya moved to the Berlin office.")
    clock["now"] = NOW + timedelta(hours=2, minutes=31)
    _work(temp_db, clock)

    assert len(fake_cognee.improve_calls) == 2
    assert any("Berlin" in text for text in fake_cognee.graph["ivo_memory"])
    merged_counts = [json.loads(job["result_json"]).get("merged_write_count") for job in _jobs(temp_db, "memory_session_merge")]
    assert merged_counts == [1, 2]


# --- Retrieval ---------------------------------------------------------------


def test_should_retrieve_false_never_queries_cognee(temp_db, fake_cognee, fake_jev):
    fake_jev.memory = {"should_store": False, "should_retrieve": False}

    result = _route("What is the capital of France?")

    assert fake_cognee.search_calls == []
    assert result["retrieval_triggered"] is False
    assert result["memory_retrieval_decision"]["should_retrieve"] is False


def test_should_retrieve_true_queries_main_graph_and_injects_memory(temp_db, fake_cognee, fake_jev):
    get_cognee_memory().remember_permanent(["The user's usual email provider is Fastmail."])
    fake_jev.memory = {"should_store": False, "should_retrieve": True}

    result = _route("What email provider do I normally use?")

    call = fake_cognee.search_calls[-1]
    assert call["datasets"] == ["ivo_memory"] and call["query_type"] == "SUMMARIES"
    [block] = _memory_blocks(result["messages"])
    assert "Fastmail" in block.content
    assert "not the current conversation" in block.content
    assert result["retrieved_memories"] == [{"kind": "long_term", "content": "The user's usual email provider is Fastmail.", "source": "cognee"}]


def test_no_relevant_memory_leaves_the_query_untouched(temp_db, fake_cognee, fake_jev):
    fake_jev.memory = {"should_store": False, "should_retrieve": True}

    result = _route("What email provider do I normally use?")

    assert result["retrieval_triggered"] is False
    assert [m.content for m in _conversation(result["messages"])] == ["What email provider do I normally use?"]


def test_recalled_memory_already_in_context_is_not_injected_again(temp_db, fake_cognee, fake_jev):
    get_cognee_memory().remember_permanent(["The user's usual email provider is Fastmail."])
    fake_jev.memory = {"should_store": False, "should_retrieve": True}
    messages = [
        AIMessage(content="Earlier: The user's usual email provider is Fastmail."),
        HumanMessage(content="Which email provider do I use?"),
    ]

    result = _route("", messages=messages)

    assert result["retrieval_triggered"] is False


def test_sessions_are_never_searched_before_merge(temp_db, fake_cognee, fake_jev, clock):
    _store_turn(temp_db, clock, "s1", "My manager is Priya.")
    fake_jev.memory = {"should_store": False, "should_retrieve": True}

    result = _route("Who is my manager Priya?")

    assert result["retrieval_triggered"] is False


def test_trivial_messages_skip_jev_entirely(temp_db, fake_cognee, fake_jev):
    for text in ["hello", "thanks", "17 * 23"]:
        assert _route(text)["memory_retrieval_decision"]["source"] == "rule"
        assert node_consolidate(_completed_state("s1", text, "Hi!"))["memory_storage_decision"]["source"] == "rule"
    assert fake_jev.calls == []


def test_retrieval_and_storage_are_separate_jev_calls(temp_db, fake_cognee, fake_jev):
    fake_jev.memory = {"should_store": True, "should_retrieve": True}

    routed = _route("I moved to Berlin last month.")
    assert routed["memory_storage_decision"] is None
    assert routed["memory_retrieval_decision"]["should_retrieve"] is True
    assert [call["kind"] for call in fake_jev.calls] == ["retrieve"]
    assert "Assistant reply" not in fake_jev.calls[0]["user"]

    stored = node_consolidate(_completed_state("s1", "I moved to Berlin last month.", "Noted, Berlin it is."))
    assert stored["memory_storage_decision"]["should_store"] is True
    assert [call["kind"] for call in fake_jev.calls] == ["retrieve", "store"]
    assert "Assistant reply: Noted, Berlin it is." in fake_jev.calls[1]["user"]


def test_retrieval_prompt_favors_recall_and_storage_prompt_sees_the_answer():
    from src.memory.jev import RETRIEVAL_DECISION_PROMPT, STORAGE_DECISION_PROMPT

    assert "When unsure, answer true" in RETRIEVAL_DECISION_PROMPT
    assert '"What is the capital of France?" -> {"should_retrieve": false}' in RETRIEVAL_DECISION_PROMPT
    assert '"Any ideas for the weekend?" -> {"should_retrieve": true}' in RETRIEVAL_DECISION_PROMPT
    assert "should_store" not in RETRIEVAL_DECISION_PROMPT
    assert "should_retrieve" not in STORAGE_DECISION_PROMPT
    assert "assistant's final reply" in STORAGE_DECISION_PROMPT


def test_approval_resume_does_not_call_jev_again(temp_db, fake_cognee, fake_jev):
    result = node_memory_router({"messages": [HumanMessage(content="Book it")], "session_id": "s1", "approval_status": "APPROVED"})

    assert fake_jev.calls == []
    assert result["memory_retrieval_decision"] is None


def test_disabled_flags_skip_jev_and_cognee(temp_db, fake_cognee, fake_jev, monkeypatch):
    from dataclasses import replace

    memory = get_cognee_memory()
    monkeypatch.setattr(memory, "config", replace(memory.config, storage_enabled=False, retrieval_enabled=False))

    result = _route("What email provider do I normally use?")

    assert fake_jev.calls == [] and fake_cognee.search_calls == []
    assert result["retrieval_triggered"] is False


def test_storage_flag_off_skips_the_storage_call_and_session_writes(temp_db, fake_cognee, fake_jev, monkeypatch):
    from dataclasses import replace

    memory = get_cognee_memory()
    monkeypatch.setattr(memory, "config", replace(memory.config, storage_enabled=False))
    fake_jev.memory = {"should_store": True, "should_retrieve": False}

    result = node_consolidate(_completed_state("s1", "Remember that I prefer short responses.", "Got it."))

    assert result["memory_job_ids"] == []
    assert result["memory_storage_decision"] is None
    assert fake_jev.calls == []


def test_retrieval_flag_off_skips_the_retrieval_call(temp_db, fake_cognee, fake_jev, monkeypatch):
    from dataclasses import replace

    memory = get_cognee_memory()
    monkeypatch.setattr(memory, "config", replace(memory.config, retrieval_enabled=False))

    result = _route("What email provider do I normally use?")

    assert result["memory_retrieval_decision"] is None
    assert fake_jev.calls == [] and fake_cognee.search_calls == []


# --- Context management stays in charge ---------------------------------------


def test_short_term_context_runs_before_the_memory_router():
    graph = build_agent_graph().get_graph()
    edges = {(edge.source, edge.target) for edge in graph.edges}

    assert ("ingest", "manage_memory") in edges
    assert ("manage_memory", "memory_router") in edges
    assert ("memory_router", "agent") in edges


def test_memory_router_never_drops_conversation_messages(temp_db, fake_cognee, fake_jev):
    get_cognee_memory().remember_permanent(["The user's usual email provider is Fastmail."])
    fake_jev.memory = {"should_store": True, "should_retrieve": True}
    history = [
        SystemMessage(content="[Conversation Summary] Earlier we planned a trip."),
        HumanMessage(content="Plan the trip."),
        AIMessage(content="Here is a plan."),
        HumanMessage(content="Email it with my usual email provider."),
    ]

    result = _route("", messages=list(history))

    conversation = _conversation(result["messages"])
    assert conversation[: len(history)] == history
    assert len(conversation) == len(history) + 1


# --- Tool calling --------------------------------------------------------------


def _tool_state(name, args, user_text):
    return {
        "messages": [HumanMessage(content=user_text), AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": "call-1"}])],
        "session_id": "tools-session",
        "approval_status": None,
        "loop_count": 1,
    }


def _task_count(db_path):
    return _rows(db_path, "SELECT COUNT(*) AS n FROM tasks")[0]["n"]


def test_jev_escalates_unexpected_medium_risk_call_to_hitl(temp_db, fake_jev):
    fake_jev.tool = {"requires_approval": True, "reason": "user did not ask for a task"}

    result = node_tools(_tool_state("create_task", {"title": "Wire money"}, "What's the weather?"))

    assert result["approval_status"] == "PENDING"
    assert result["pending_approval_id"]
    assert _task_count(temp_db) == 0
    assert "waiting for human approval" in result["messages"][0].content
    [request] = _rows(temp_db, "SELECT * FROM approval_requests")
    assert request["tool_name"] == "create_task" and "Jev review" in request["reason"]


def test_jev_approval_lets_medium_risk_call_run_normally(temp_db, fake_jev):
    fake_jev.tool = {"requires_approval": False, "reason": ""}

    result = node_tools(_tool_state("create_task", {"title": "Buy milk"}, "Add a task to buy milk"))

    assert result.get("approval_status") is None
    assert _task_count(temp_db) == 1
    assert [call["kind"] for call in fake_jev.calls] == ["tool"]


def test_jev_cannot_bypass_hitl_for_high_risk_tools(temp_db, fake_jev):
    fake_jev.tool = {"requires_approval": False, "reason": "looks fine"}

    result = node_tools(_tool_state("schedule_job", {"cron_or_timestamp": "2026-10-05 09:00", "task_payload": "ping"}, "Schedule a ping"))

    assert result["approval_status"] == "PENDING"
    # High-risk calls are decided by policy alone; Jev is not even consulted.
    assert fake_jev.calls == []


def test_low_risk_reads_are_not_sent_to_jev(temp_db, fake_jev):
    node_tools(_tool_state("list_tasks", {}, "What are my tasks?"))

    assert fake_jev.calls == []


def test_jev_failure_keeps_existing_policy_outcome(temp_db, fake_jev):
    fake_jev.fail = True

    result = node_tools(_tool_state("create_task", {"title": "Buy milk"}, "Add a task to buy milk"))

    assert result.get("approval_status") is None
    assert _task_count(temp_db) == 1


def test_escalated_call_runs_after_human_approval(temp_db, fake_jev, monkeypatch):
    from src.harness.graph import resume_graph_after_approval

    fake_jev.tool = {"requires_approval": True, "reason": "double-check"}
    paused = node_tools(_tool_state("create_task", {"title": "Renew passport"}, "Remind me about my passport"))

    resumed = resume_graph_after_approval(paused["pending_approval_id"], "APPROVED")

    assert resumed["status"] == "APPROVED"
    assert _task_count(temp_db) == 1


# --- Failure handling ------------------------------------------------------------


def test_jev_failure_falls_back_to_retrieve_without_storing(temp_db, fake_cognee, fake_jev):
    fake_jev.fail = True

    retrieval = _route("What email provider do I normally use?")["memory_retrieval_decision"]
    storage = node_consolidate(_completed_state("s1", "My email provider is Fastmail.", "Noted."))["memory_storage_decision"]

    assert retrieval["source"] == "fallback" and retrieval["error_category"] == "TimeoutError"
    assert retrieval["should_retrieve"] is True
    assert storage["source"] == "fallback" and storage["error_category"] == "TimeoutError"
    assert storage["should_store"] is False


@pytest.mark.parametrize("raw", ["not json", '{"should_store": "yes", "should_retrieve": "yes"}', "[true, false]"])
def test_malformed_jev_output_is_rejected_safely(temp_db, fake_cognee, fake_jev, raw):
    fake_jev.raw = raw

    retrieval = _route("What email provider do I normally use?")["memory_retrieval_decision"]
    result = node_consolidate(_completed_state("s1", "My email provider is Fastmail.", "Noted."))

    assert retrieval["source"] == "fallback" and retrieval["should_retrieve"] is True
    assert result["memory_storage_decision"]["source"] == "fallback"
    assert result["memory_storage_decision"]["should_store"] is False
    assert result["memory_job_ids"] == []


def test_cognee_retrieval_failure_does_not_break_the_turn(temp_db, fake_cognee, fake_jev, monkeypatch):
    async def explode(**kwargs):
        raise RuntimeError("vector store offline")

    monkeypatch.setattr(fake_cognee, "search", explode)
    fake_jev.memory = {"should_store": False, "should_retrieve": True}

    result = _route("What email provider do I normally use?")

    assert result["retrieval_triggered"] is False
    assert [m.content for m in _conversation(result["messages"])] == ["What email provider do I normally use?"]


def test_session_write_failure_retries_and_does_not_schedule_a_merge(temp_db, fake_cognee, clock, monkeypatch):
    async def explode(*args, **kwargs):
        raise ConnectionError("cache down")

    monkeypatch.setattr(fake_cognee, "remember", explode)

    steps = _store_turn(temp_db, clock, "s1", "My manager is Priya.")

    assert steps[0].status == "RETRYING"
    assert _jobs(temp_db, "memory_session_merge") == []


@pytest.mark.parametrize(
    "improve_result",
    [
        {"status": "errored", "error": "graph write failed"},
        {"status": "skipped", "lock_held": True, "rerun_requested": False},
    ],
)
def test_merge_failure_is_retried_and_later_succeeds(temp_db, fake_cognee, clock, improve_result):
    _store_turn(temp_db, clock, "s1", "My manager is Priya.")
    stages = [type("Stage", (), {"reason": "lock_held"})()] if improve_result.get("lock_held") else []
    fake_cognee.improve_result = fake_cognee.ImproveResult(
        status=improve_result["status"], stages=stages, rerun_requested=improve_result.get("rerun_requested", False), error=improve_result.get("error")
    )

    clock["now"] = NOW + timedelta(minutes=31)
    [failed] = _work(temp_db, clock, steps=1)
    assert failed.status == "RETRYING"

    fake_cognee.improve_result = None
    clock["now"] = NOW + timedelta(hours=1)
    _work(temp_db, clock)
    assert any("Priya" in text for text in fake_cognee.graph["ivo_memory"])


def test_concurrent_held_merge_that_covers_entries_counts_as_success(temp_db, fake_cognee, clock):
    _store_turn(temp_db, clock, "s1", "My manager is Priya.")
    fake_cognee.improve_result = fake_cognee.ImproveResult(
        status="skipped", stages=[type("Stage", (), {"reason": "lock_held"})()], rerun_requested=True
    )

    clock["now"] = NOW + timedelta(minutes=31)
    [step] = _work(temp_db, clock)

    assert step.status == "SUCCEEDED"
    assert json.loads(_jobs(temp_db, "memory_session_merge")[0]["result_json"])["outcome"] == "covered"


def test_concurrent_sessions_stay_isolated(temp_db, fake_cognee, clock):
    _store_turn(temp_db, clock, "alpha", "Alpha project uses Rust.")
    _store_turn(temp_db, clock, "beta", "Beta project uses Go.")
    _turn(temp_db, "beta", NOW + timedelta(minutes=25))

    clock["now"] = NOW + timedelta(minutes=31)
    _work(temp_db, clock)

    alpha, beta = session_key("default_user", "alpha"), session_key("default_user", "beta")
    assert fake_cognee.sessions[alpha] == ["Alpha project uses Rust."]
    assert fake_cognee.sessions[beta] == ["Beta project uses Go."]
    # Only the idle session merged; the still-active one was deferred.
    assert fake_cognee.improve_calls == [{"dataset": "ivo_memory", "session_ids": [alpha]}]
    assert fake_cognee.graph["ivo_memory"] == ["Alpha project uses Rust."]


def test_session_keys_are_scoped_by_user_and_collision_safe():
    assert session_key("default_user", "s1") != session_key("other_user", "s1")
    assert session_key("u", "a/b") != session_key("u", "a_b")
    assert session_key("u", "plain-id_1") == "u__plain-id_1"


def test_force_merge_endpoint_merges_without_waiting(temp_db, fake_cognee, clock):
    from fastapi.testclient import TestClient

    from src.api.server import app

    _store_turn(temp_db, clock, "s1", "My manager is Priya.")
    response = TestClient(app).post("/api/memory/sessions/s1/merge")
    clock["now"] = NOW + timedelta(minutes=1)
    _work(temp_db, clock)

    assert response.json()["status"] == "queued"
    assert len(fake_cognee.improve_calls) == 1


def test_job_status_endpoint_reports_merge_result_without_payload(temp_db, fake_cognee, clock):
    from fastapi.testclient import TestClient

    from src.api.server import app

    client = TestClient(app)
    _store_turn(temp_db, clock, "s1", "My manager is Priya.")
    queued = client.post("/api/memory/sessions/s1/merge").json()
    clock["now"] = NOW + timedelta(minutes=1)
    _work(temp_db, clock)

    job = client.get(f"/api/memory/observability/jobs/{queued['job_id']}").json()
    nothing = client.post("/api/memory/sessions/empty-session/merge").json()
    clock["now"] = NOW + timedelta(minutes=2)
    _work(temp_db, clock)
    empty = client.get(f"/api/memory/observability/jobs/{nothing['job_id']}").json()

    assert job["status"] == "SUCCEEDED" and job["result"]["merged"] is True
    assert "payload" not in job and "Priya" not in json.dumps(job)
    assert empty["status"] == "SUCCEEDED" and empty["result"]["skipped"] == "nothing_to_merge"
    assert client.get("/api/memory/observability/jobs/does-not-exist").status_code == 404
