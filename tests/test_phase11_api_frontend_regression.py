from fastapi.testclient import TestClient

from src.api.server import app
from src.db import init_db

client = TestClient(app)


def test_api_response_shapes_unchanged(tmp_path, monkeypatch):
    db_file = tmp_path / "phase11_api.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)

    chat = client.post("/api/chat", json={"message": "Hello API shape", "session_id": "phase11-api", "provider": "openai", "model_name": "gpt-4o-mini"})
    memory = client.get("/api/memory")
    full = client.get("/api/memory/full")
    approvals = client.get("/api/approvals")
    tables = client.get("/api/data/tables")
    models = client.get("/api/models")

    assert chat.status_code == 200
    assert {"session_id", "session_title", "response", "retrieval_triggered", "retrieved_memories", "pending_approval_id", "approval_status", "iterations", "tools_used", "loop_events", "loop_trace"} <= set(chat.json())
    assert {"backend", "enabled", "available", "error", "dataset_name", "search_type", "storage_enabled", "retrieval_enabled", "session_idle_timeout_minutes"} <= set(memory.json())
    assert {"backend", "query", "memories", "error", "soul_md"} <= set(full.json())
    assert set(approvals.json()) == {"approval_requests"}
    assert {"tables"} <= set(tables.json())
    assert {"catalog", "memory_defaults"} <= set(models.json())


def test_data_table_endpoint_shape_includes_phase_tables(tmp_path, monkeypatch):
    db_file = tmp_path / "phase11_data_api.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)

    tables = client.get("/api/data/tables").json()["tables"]
    assert "memory_jobs" in tables
    assert "structured_episodes" in tables
    assert "skill_versions" in tables

    table = client.get("/api/data/table/memory_jobs")
    assert table.status_code == 200
    assert {"table", "total_rows", "columns", "rows"} <= set(table.json())


def test_frontend_memory_ops_component_renders_empty_and_error_states_textually():
    content = open("frontend/src/components/MemoryObservabilityCockpit.jsx", encoding="utf-8").read()

    assert "Memory Ops" in content
    assert "No memory jobs found." in content
    assert "No worker heartbeats recorded" in content
    assert "Failed to load memory observability" in content
    assert "Run a trace" in content


def test_frontend_memory_ops_uses_observability_endpoints_only_for_panel_loads():
    content = open("frontend/src/components/MemoryObservabilityCockpit.jsx", encoding="utf-8").read()

    assert "/api/memory/observability/overview" in content
    assert "/api/memory/observability/retrieval/trace" in content
    forbidden_write_endpoints = ["/api/chat", "/api/memory/fact", "/api/skills'", 'method: "PUT"', "method: 'PUT'", 'method: "DELETE"', "method: 'DELETE'"]
    for forbidden in forbidden_write_endpoints:
        assert forbidden not in content


def test_memory_ops_tab_is_wired_without_changing_api_shapes():
    app_content = open("frontend/src/App.jsx", encoding="utf-8").read()

    assert "MemoryObservabilityCockpit" in app_content
    assert "memoryOps" in app_content or "Memory Ops" in app_content
