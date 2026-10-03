import sqlite3
import zipfile
from datetime import datetime

import pytest

from src.db import init_db
from src.memory.cognee_memory import (
    RETRIEVED_MEMORY_HEADER,
    CogneeMemory,
    CogneeUnavailableError,
    RecalledMemory,
    RecallResult,
    _flatten_search_results,
    _supported_kwargs,
    get_cognee_memory,
    prepare_cognee_environment,
)
from src.memory.config import CogneeMemoryConfig
from src.memory.job_handlers import CogneeIngestJobHandler, MemorySessionMergeJobHandler, MemorySessionWriteJobHandler
from src.memory.jobs import build_cognee_ingest_job_spec, build_memory_session_merge_job_spec


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "cognee_memory.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file


def test_prepare_environment_sets_storage_defaults_without_overriding(tmp_path):
    config = CogneeMemoryConfig(data_dir=str(tmp_path / "cg"))
    env = {"OPENAI_API_KEY": "sk-test-openai", "TELEMETRY_DISABLED": "0"}

    applied = prepare_cognee_environment(config, environ=env)

    assert env["SYSTEM_ROOT_DIRECTORY"] == str(tmp_path / "cg" / "system")
    assert env["DATA_ROOT_DIRECTORY"] == str(tmp_path / "cg" / "data")
    assert env["IMPROVE_AUTO_ENABLED"] == "false"
    assert env["TELEMETRY_DISABLED"] == "0" and "TELEMETRY_DISABLED" not in applied
    # Model keys are applied through cognee.config, never copied into env vars.
    assert "LLM_API_KEY" not in env and "EMBEDDING_API_KEY" not in env


@pytest.mark.parametrize(
    "provider,key_env,llm_model,embedding_model,dimensions",
    [
        ("openai", "OPENAI_API_KEY", "openai/gpt-4o-mini", "openai/text-embedding-3-small", 1536),
        ("gemini", "GOOGLE_API_KEY", "gemini/gemini-3.5-flash-lite", "gemini/gemini-embedding-001", 3072),
    ],
)
def test_cognee_models_follow_ai_provider(monkeypatch, provider, key_env, llm_model, embedding_model, dimensions):
    from src.memory.cognee_memory import cognee_model_settings

    monkeypatch.setenv("AI_PROVIDER", provider)
    monkeypatch.setenv(key_env, f"{provider}-test-key")

    settings = cognee_model_settings()

    assert settings["llm"] == {"llm_provider": provider, "llm_model": llm_model, "llm_api_key": f"{provider}-test-key"}
    assert settings["embedding"]["embedding_model"] == embedding_model
    assert settings["embedding"]["embedding_dimensions"] == dimensions
    assert settings["embedding"]["embedding_api_key"] == f"{provider}-test-key"


def test_cognee_receives_model_settings_after_import(monkeypatch, tmp_path):
    from tests.conftest import FakeCogneeModule

    applied = {}

    class Config(FakeCogneeModule._Config):
        def set_llm_config(self, values):
            applied["llm"] = values

        def set_embedding_config(self, values):
            applied["embedding"] = values

    fake = FakeCogneeModule()
    fake.config = Config()
    monkeypatch.setitem(__import__("sys").modules, "cognee", fake)
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.setenv("GOOGLE_API_KEY", "g-key")

    memory = CogneeMemory(config=CogneeMemoryConfig(data_dir=str(tmp_path / "cg")))

    assert memory.status()["available"] is True
    assert applied["llm"]["llm_model"] == "gemini/gemini-3.5-flash-lite"
    assert applied["embedding"]["embedding_model"] == "gemini/gemini-embedding-001"
    assert memory.status()["ai_provider"] == "gemini"


def test_flatten_search_results_handles_cognee_result_shapes():
    class ScoredResult:
        def __init__(self, payload):
            self.payload = payload

    raw = [
        "plain answer",
        {"search_result": ["nested context", "plain answer"], "dataset_name": "ivo_memory"},
        {"text": "chunk text"},
        ScoredResult({"text": "scored chunk"}),
        {"irrelevant": 1},
        "   ",
    ]

    assert _flatten_search_results(raw) == ["plain answer", "nested context", "chunk text", "scored chunk"]


def test_supported_kwargs_drops_arguments_older_cognee_does_not_accept():
    async def old_search(query_text, query_type=None, datasets=None):
        return []

    async def new_search(**kwargs):
        return []

    kwargs = {"query_text": "q", "datasets": ["d"], "only_context": True, "top_k": 3}

    assert _supported_kwargs(old_search, kwargs) == {"query_text": "q", "datasets": ["d"]}
    assert _supported_kwargs(new_search, kwargs) == kwargs


def test_context_block_respects_token_budget():
    result = RecallResult(
        memories=[RecalledMemory(content="short fact"), RecalledMemory(content="x " * 4000)],
        search_type="GRAPH_COMPLETION",
        available=True,
    )

    block = result.to_context_block(token_budget=200)

    assert block.startswith(RETRIEVED_MEMORY_HEADER)
    assert "- short fact" in block
    assert len(block) // 4 <= 200 + 20
    assert RecallResult(memories=[], search_type="CHUNKS", available=True).to_context_block(100) == ""


def test_disabled_memory_reports_reason_and_recall_is_empty():
    memory = CogneeMemory(config=CogneeMemoryConfig(enabled=False))

    status = memory.status()
    recall = memory.recall("anything at all")

    assert status["available"] is False
    assert "disabled" in status["error"]
    assert recall.memories == [] and recall.available is False
    with pytest.raises(CogneeUnavailableError):
        memory.remember_in_session("text", user_id="default_user", session_id="s1")


def test_permanent_writes_and_recall_use_main_dataset_and_summaries(fake_cognee):
    memory = get_cognee_memory()
    memory.remember_permanent(["Fact about the user: prefers tea over coffee", "  "])

    result = memory.recall("does the user prefer coffee?")

    assert fake_cognee.remember_calls == [{"dataset_name": "ivo_memory", "session_id": None, "self_improvement": False}]
    assert [item.content for item in result.memories] == ["Fact about the user: prefers tea over coffee"]
    call = fake_cognee.search_calls[-1]
    assert call["query_type"] == "SUMMARIES"
    assert call["only_context"] is False
    assert call["datasets"] == ["ivo_memory"]


@pytest.mark.parametrize("search_type", ["GRAPH_COMPLETION", "RAG_COMPLETION"])
def test_completion_search_types_request_context_only(fake_cognee, search_type):
    get_cognee_memory().recall("anything here", search_type=search_type)

    assert fake_cognee.search_calls[-1]["only_context"] is True
    assert fake_cognee.search_calls[-1]["query_type"] == search_type


def test_non_default_user_gets_its_own_main_graph(fake_cognee):
    memory = get_cognee_memory()

    memory.remember_permanent(["Bob likes chess"], user_id="bob")
    memory.recall("does anyone like chess?", user_id="bob")

    assert fake_cognee.remember_calls[-1]["dataset_name"] == "ivo_memory_bob"
    assert fake_cognee.search_calls[-1]["datasets"] == ["ivo_memory_bob"]
    assert memory.recall("does anyone like chess?").memories == []


def test_chunks_search_does_not_request_context_only(fake_cognee):
    get_cognee_memory().recall("anything here", search_type="chunks")

    assert fake_cognee.search_calls[-1]["only_context"] is False
    assert fake_cognee.search_calls[-1]["query_type"] == "CHUNKS"


def test_recall_failure_is_reported_not_raised(fake_cognee, monkeypatch):
    async def explode(**kwargs):
        raise RuntimeError("vector store offline")

    monkeypatch.setattr(fake_cognee, "search", explode)

    result = get_cognee_memory().recall("will this fail?")

    assert result.memories == []
    assert "vector store offline" in result.error


def test_merge_jobs_are_keyed_by_due_time():
    due = datetime(2026, 10, 3, 9, 30, 0, 500)
    first = build_memory_session_merge_job_spec(user_id="u", session_id="s", run_at=due)
    same = build_memory_session_merge_job_spec(user_id="u", session_id="s", run_at=due)
    later = build_memory_session_merge_job_spec(user_id="u", session_id="s", run_at=datetime(2026, 10, 3, 9, 31))
    other_session = build_memory_session_merge_job_spec(user_id="u", session_id="t", run_at=due)
    forced = build_memory_session_merge_job_spec(user_id="u", session_id="s", run_at=due, force=True)

    assert first.idempotency_key == same.idempotency_key
    assert len({first.idempotency_key, later.idempotency_key, other_session.idempotency_key, forced.idempotency_key}) == 4
    assert first.available_at == "2026-10-03 09:30:00"
    assert first.priority > 100


def test_ingest_spec_rejects_empty_documents_and_is_content_keyed():
    with pytest.raises(ValueError):
        build_cognee_ingest_job_spec(documents=["  "], source="test")

    one = build_cognee_ingest_job_spec(documents=[" a "], source="x")
    two = build_cognee_ingest_job_spec(documents=["a"], source="y")

    assert one.payload["documents"] == ["a"]
    assert one.idempotency_key == two.idempotency_key


def test_ingest_handler_writes_permanent_memory(temp_db, fake_cognee):
    result = CogneeIngestJobHandler().handle(job={}, payload={"schema_version": 1, "documents": ["fact one", "fact two"]})

    assert result.success
    assert fake_cognee.graph["ivo_memory"] == ["fact one", "fact two"]
    assert fake_cognee.sessions == {}


def test_handlers_fail_fast_without_retry_when_cognee_unavailable(temp_db):
    ingest = CogneeIngestJobHandler().handle(job={}, payload={"schema_version": 1, "documents": ["fact"]})
    write = MemorySessionWriteJobHandler().handle(job={}, payload={"schema_version": 1, "session_id": "s1", "text": "fact"})
    invalid = CogneeIngestJobHandler().handle(job={}, payload={"schema_version": 1, "documents": [{"text": "old shape"}]})
    missing = MemorySessionMergeJobHandler().handle(job={}, payload={"schema_version": 1})

    assert (ingest.success, ingest.retryable) == (False, False)
    assert (write.success, write.retryable) == (False, False)
    assert (invalid.success, invalid.retryable) == (False, False)
    assert (missing.success, missing.retryable) == (False, False)


def test_backfill_imports_legacy_tables_idempotently(temp_db):
    from src.memory.cognee_backfill import backfill_legacy_memory

    conn = sqlite3.connect(temp_db)
    try:
        conn.execute("INSERT INTO facts (category, fact_text, source, confidence, created_at) VALUES ('pref', 'Likes tea', 'user', '1', datetime('now'))")
        conn.execute("INSERT INTO skills (name, description, trigger_keywords, execution_steps) VALUES ('digest', 'Inbox digest', 'inbox', 'fetch; summarize')")
        conn.commit()
    finally:
        conn.close()

    dry = backfill_legacy_memory(temp_db, dry_run=True)
    first = backfill_legacy_memory(temp_db)
    again = backfill_legacy_memory(temp_db)

    assert dry["documents_by_table"]["facts"] == 1
    assert dry["documents_by_table"]["skills"] == 1
    assert dry["jobs_queued"] == 0
    assert first["jobs_queued"] == 1
    assert again["jobs_queued"] == 0 and again["jobs_already_present"] == 1


def test_backup_round_trips_cognee_dir_and_blocks_zip_slip(tmp_path, monkeypatch):
    from src.personal_os import backup

    cognee_dir = tmp_path / "cognee"
    (cognee_dir / "system").mkdir(parents=True)
    (cognee_dir / "system" / "graph.db").write_bytes(b"graph-bytes")
    monkeypatch.setattr(backup, "_cognee_dir", lambda: cognee_dir)
    db_file = tmp_path / "state.db"
    init_db(db_file)
    monkeypatch.setattr(backup, "DB_PATH", db_file)
    for name in ("SOUL_PATH", "MEMORY_PATH", "SKILL_PATH"):
        monkeypatch.setattr(backup, name, tmp_path / f"{name}.md")

    exported = backup.export_agent_backup(output_dir=tmp_path / "backups")
    assert "cognee/" in exported["packed_files"]

    (cognee_dir / "system" / "graph.db").write_bytes(b"changed")
    with zipfile.ZipFile(exported["backup_path"], "a") as zf:
        zf.writestr("cognee/../escaped.txt", "nope")

    restored = backup.restore_agent_backup(exported["backup_path"], db_path=db_file)

    assert "cognee/" in restored["restored_files"]
    assert (cognee_dir / "system" / "graph.db").read_bytes() == b"graph-bytes"
    assert not (tmp_path / "escaped.txt").exists()


def _graph_payload():
    return {
        "nodes": [
            {"id": "e1", "name": "khusham", "type": "Entity", "description": "The user", "color": "#f00"},
            {"id": "e2", "name": "chandigarh", "type": "Entity", "text": "x " * 500},
            {"id": "t1", "name": "person", "type": "EntityType"},
            {"id": "c1", "name": "Session chunk", "type": "DocumentChunk"},
        ],
        "links": [
            {"source": "c1", "target": "e1", "relation": "contains"},
            {"source": "c1", "target": "e2", "relation": "contains"},
            {"source": "e1", "target": "t1", "relation": "is_a"},
            {"source": "e1", "target": "e1", "relation": "self"},
        ],
    }


def test_graph_snapshot_compacts_and_filters_documents(fake_cognee):
    calls = []

    async def visualize_graph_json(dataset=None, include_session_events=True, max_nodes=500, **kwargs):
        calls.append({"dataset": dataset, "include_session_events": include_session_events, "max_nodes": max_nodes})
        return _graph_payload()

    fake_cognee.visualize_graph_json = visualize_graph_json
    memory = get_cognee_memory()

    full = memory.graph_snapshot(max_nodes=50, include_documents=True)
    knowledge = memory.graph_snapshot()

    assert calls[0] == {"dataset": "ivo_memory", "include_session_events": False, "max_nodes": 50}
    assert {n["id"] for n in full["nodes"]} == {"e1", "e2", "t1", "c1"}
    assert full["node_types"] == {"Entity": 2, "EntityType": 1, "DocumentChunk": 1}
    # Self-loops are dropped; degrees count only kept links.
    assert len(full["links"]) == 3
    assert {n["id"]: n["degree"] for n in full["nodes"]}["c1"] == 2
    assert len(next(n for n in full["nodes"] if n["id"] == "e2")["detail"]) <= 400
    assert {n["id"] for n in knowledge["nodes"]} == {"e1", "e2", "t1"}
    assert knowledge["links"] == [{"source": "e1", "target": "t1", "relation": "is_a"}]


def test_graph_snapshot_treats_missing_dataset_as_empty(fake_cognee):
    async def visualize_graph_json(**kwargs):
        raise type("DatasetNotFoundError", (Exception,), {})("Dataset ivo_memory not found")

    fake_cognee.visualize_graph_json = visualize_graph_json

    assert get_cognee_memory().graph_snapshot()["nodes"] == []


def test_graph_endpoint_bounds_max_nodes_and_reports_unavailable(fake_cognee, monkeypatch):
    from fastapi.testclient import TestClient

    from src.api.server import app

    seen = {}

    async def visualize_graph_json(max_nodes=500, **kwargs):
        seen["max_nodes"] = max_nodes
        return _graph_payload()

    fake_cognee.visualize_graph_json = visualize_graph_json
    client = TestClient(app)

    data = client.get("/api/memory/graph?max_nodes=999999&include_documents=true").json()
    assert data["available"] is True and len(data["nodes"]) == 4
    assert seen["max_nodes"] == 1000

    from src.memory.cognee_memory import CogneeMemory, set_cognee_memory

    set_cognee_memory(CogneeMemory(config=CogneeMemoryConfig(enabled=False)))
    unavailable = client.get("/api/memory/graph").json()
    assert unavailable["available"] is False and unavailable["nodes"] == []
