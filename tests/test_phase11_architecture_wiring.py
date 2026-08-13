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


def test_retrieval_planner_and_assembler_have_no_llm_calls_or_writes():
    combined = "\n".join(_text(path) for path in ["src/memory/retrieval_planner.py", "src/memory/context_assembler.py"])
    forbidden = [
        "resolve_secondary_llm",
        "get_secondary_llm",
        ".invoke(",
        "INSERT",
        "UPDATE",
        "DELETE",
        "commit(",
        "enqueue_",
        "add_explicit_fact",
        "record_used",
        "reload_active_skills",
    ]

    for token in forbidden:
        assert token not in combined


def test_retrieval_sources_do_not_write_or_mutate_runtime_state():
    text = _text("src/memory/retrieval_sources.py")
    forbidden = [
        "upsert_embedding",
        "add_explicit_fact",
        "record_used",
        "reload_active_skills",
        "INSERT INTO",
        "UPDATE ",
        "DELETE FROM",
        "commit(",
    ]

    for token in forbidden:
        assert token not in text


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
        "create_version",
        "enqueue_",
        "add_explicit_fact",
        "record_used",
        "reload_active_skills",
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
    from src.memory.job_handlers import NoOpMemoryJobHandler, build_default_handler_registry

    registry = build_default_handler_registry()

    assert registry["summary_generation"].__class__.__name__ == "SummaryGenerationJobHandler"
    assert registry["episode_generation"].__class__.__name__ == "EpisodeGenerationJobHandler"
    assert registry["semantic_candidate_extraction"].__class__.__name__ == "SemanticCandidateExtractionJobHandler"
    assert registry["semantic_consolidation"].__class__.__name__ == "SemanticConsolidationJobHandler"
    assert registry["procedural_candidate_generation"].__class__.__name__ == "ProceduralCandidateGenerationJobHandler"
    assert registry["skill_promotion"].__class__.__name__ == "SkillPromotionJobHandler"
    assert isinstance(registry["procedural_consolidation"], NoOpMemoryJobHandler)


def test_generated_skill_path_contract_documented_and_implemented():
    text = _text("src/memory/skill_files.py")
    assert "skills" in text
    assert "generated" in text
    assert "v{int(version):04d}" in text or "vNNNN" in _text("docs/memory-architecture.md")


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
    for term in ["primary", "secondary", "memory_jobs", "structured", "semantic", "procedural", "retrieval", "observability", "legacy"]:
        assert term in architecture


def test_no_secret_examples_in_observability_frontend():
    combined = _text("src/memory/observability.py") + "\n" + _text("frontend/src/components/MemoryObservabilityCockpit.jsx")
    literal_secret_patterns = [r"sk-[A-Za-z0-9]{8,}", r"Bearer [A-Za-z0-9._-]{8,}"]
    for pattern in literal_secret_patterns:
        assert re.search(pattern, combined) is None

