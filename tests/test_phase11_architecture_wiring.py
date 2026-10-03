import ast
import re
from pathlib import Path


def _text(path):
    return Path(path).read_text(encoding="utf-8-sig")


def test_no_worker_auto_start_from_startup_or_chat_graph():
    combined = "\n".join(_text(path) for path in ["src/startup.py", "src/harness/graph.py"])

    assert "run_memory_worker_loop(" not in combined
    assert "process_one_memory_job(" not in combined
    assert "start_memory_worker_runtime(" not in combined
    assert "enqueue_semantic_consolidation_job(" not in combined
    assert "maybe_enqueue_idle_semantic_consolidation(" not in combined


def test_api_starts_memory_worker_outside_the_chat_path():
    text = _text("src/api/server.py")
    assert "run_memory_worker_loop(" not in text
    assert "process_one_memory_job(" not in text
    assert "start_memory_worker_runtime(" in text


def _function_source(path, name):
    source = _text(path)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(source, node)
    raise AssertionError(f"{name} not found in {path}")


def test_chat_retrieval_node_is_read_only_and_makes_no_llm_calls():
    text = _function_source("src/harness/graph.py", "node_memory_router")
    forbidden = [
        "resolve_secondary_llm",
        "get_secondary_llm",
        ".invoke(",
        "INSERT",
        "commit(",
        "enqueue_",
        ".remember(",
        ".cognify(",
    ]

    for token in forbidden:
        assert token not in text
    assert ".recall(" in text


def test_cognee_recall_requests_context_only_and_never_writes():
    text = _function_source("src/memory/cognee_memory.py", "recall")

    assert '"only_context"' in text
    for token in ["cognee.add(", "cognee.cognify(", "enqueue_", "INSERT", "commit("]:
        assert token not in text


def test_only_the_adapter_imports_cognee():
    offenders = [
        str(path)
        for path in Path("src").rglob("*.py")
        if path.as_posix() != "src/memory/cognee_memory.py"
        and re.search(r"^\s*(import cognee|from cognee)", _text(path), re.MULTILINE)
    ]
    assert offenders == []


def test_observability_helper_has_no_sql_writes_or_mutating_repository_calls():
    text = _text("src/memory/observability.py")
    forbidden = [
        "INSERT INTO",
        "UPDATE ",
        "DELETE FROM",
        "commit(",
        "claim_next_due_job",
        "handle_job_failure",
        "recover_stale_running_jobs",
        "upsert_worker_heartbeat",
        "create_approval_request",
        "enqueue_",
        ".remember(",
        ".cognify(",
        "forget_all(",
    ]

    for token in forbidden:
        assert token not in text


def test_api_chat_return_shape_has_no_public_debug_keys():
    source = _text("src/api/server.py")
    tree = ast.parse(source)
    chat_func = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_chat_payload")
    returned_keys = set()
    for node in ast.walk(chat_func):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
            for key in node.value.keys:
                if isinstance(key, ast.Constant):
                    returned_keys.add(key.value)

    assert "debug" not in returned_keys
    assert "trace" not in returned_keys
    assert "prompt_block" not in returned_keys
    assert "retrieval_debug" not in returned_keys
    assert {"session_id", "response", "retrieval_triggered", "retrieved_memories"} <= returned_keys


def test_memory_job_handler_registry_final_shape():
    from src.memory.job_handlers import build_default_handler_registry

    registry = build_default_handler_registry()

    assert {job_type: handler.__class__.__name__ for job_type, handler in registry.items()} == {
        "summary_generation": "SummaryGenerationJobHandler",
        "cognee_ingest": "CogneeIngestJobHandler",
        "memory_session_write": "MemorySessionWriteJobHandler",
        "memory_session_merge": "MemorySessionMergeJobHandler",
    }


def test_jev_can_only_escalate_tool_calls():
    text = _function_source("src/harness/graph.py", "_jev_tool_escalation")

    # Jev is consulted only for calls policy would already run directly, and returns an
    # escalation reason or None; it never invokes tools or touches approvals itself.
    assert "policy.requires_approval" in text
    for token in ["invoke_registered_tool", "process_approval_decision", '"approved": True']:
        assert token not in text


def test_jev_is_a_router_not_an_agent():
    text = _text("src/memory/jev.py")

    for token in ["bind_tools", "invoke_registered_tool", "get_cognee_memory", "enqueue_", "create_approval_request"]:
        assert token not in text


def test_docs_exist_and_cover_required_phase11_topics():
    required = [
        "docs/memory-architecture.md",
        "docs/operator-runbook.md",
        "docs/developer-testing.md",
        "docs/api-memory-observability.md",
        "docs/memory-failure-recovery.md",
        "docs/legacy-memory-backfill.md",
    ]
    for path in required:
        assert Path(path).exists(), path

    architecture = _text("docs/memory-architecture.md").lower()
    for term in ["primary", "secondary", "memory_jobs", "cognee", "jev", "session_idle_timeout", "memory_session_merge", "should_store", "should_retrieve", "retrieval", "observability", "legacy"]:
        assert term in architecture


def test_no_secret_examples_in_observability_frontend():
    combined = _text("src/memory/observability.py") + "\n" + _text("frontend/src/components/MemoryObservabilityCockpit.jsx")
    literal_secret_patterns = [r"sk-[A-Za-z0-9]{8,}", r"Bearer [A-Za-z0-9._-]{8,}"]
    for pattern in literal_secret_patterns:
        assert re.search(pattern, combined) is None

