# Developer Testing Guide

## Full Suite

```powershell
python -m pytest -q
```

## Phase 11 Focused Suite

```powershell
python -m pytest tests/test_phase11_e2e_chat_memory_pipeline.py tests/test_phase11_e2e_worker_lifecycle.py tests/test_phase11_e2e_semantic_lifecycle.py tests/test_phase11_e2e_episodic_lifecycle.py tests/test_phase11_e2e_procedural_lifecycle.py tests/test_phase11_e2e_approval_skill_promotion.py tests/test_phase11_e2e_observability_readonly.py tests/test_phase11_startup_config_validation.py tests/test_phase11_api_frontend_regression.py tests/test_phase11_architecture_wiring.py -q
```

## Core Regression Suites

Memory jobs and worker:

```powershell
python -m pytest tests/test_phase3a_memory_jobs.py tests/test_phase3a_graph_enqueue.py tests/test_phase3b_worker_repository.py tests/test_phase3b_worker_step.py tests/test_phase3b_router_handlers.py -q
```

Short-term, episodic, semantic, procedural, retrieval, and observability:

```powershell
python -m pytest tests/test_phase5b_graph_short_term.py tests/test_phase5b_summary_job_handler.py tests/test_phase6b_episode_handler.py tests/test_phase7c_consolidation_handler.py tests/test_phase8c_skill_promotion_handler.py tests/test_phase9b_graph_retrieval_integration.py tests/test_phase10_memory_observability_api.py -q
```

API and frontend smoke:

```powershell
python -m pytest tests/test_api_server.py tests/test_frontend_api.py tests/test_p2_frontend_smoke.py tests/test_p3_frontend.py tests/test_phase10_frontend_observability.py -q
```

Frontend build:

```powershell
Set-Location frontend
npm run build
```

## Fixture Guidance

Use `tmp_path` for:

- Temporary SQLite databases.
- Temporary `.agent` workspaces.
- Temporary `.agent/skills` roots.
- Temporary `MEMORY.md`, `SOUL.md`, and `SKILL.md`.

Use `monkeypatch` to patch:

- `src.db.DB_PATH`
- `src.config.MEMORY_PATH`
- `src.config.SKILL_PATH`
- `src.memory.skill_files.SKILL_PATH`
- LLM router resolution helpers.

Do not use the real user `.agent` directory in tests.

## Fake LLM Guidance

Fake primary LLMs should implement `.invoke(messages)` and return a deterministic `AIMessage` or string-like object expected by the caller.

Fake secondary LLMs should be injected through `resolve_secondary_from_job_payload()` or the handler-specific route boundary. They should return direct JSON or fenced JSON so handler parsing is exercised.

## Worker Time Guidance

Use injected `datetime` values for:

- `process_one_memory_job(now=...)`
- `claim_next_due_job(now=...)`
- `handle_job_failure(now=...)`
- `recover_stale_running_jobs(now=...)`
- `upsert_worker_heartbeat(now=...)`

Avoid sleeps in worker tests.

## Static Scans

Worker auto-start scan:

```powershell
rg -n "run_memory_worker_loop|process_one_memory_job" src/startup.py src/api/server.py src/harness/graph.py
```

Chat/retrieval LLM scan:

```powershell
rg -n "resolve_secondary_llm|get_secondary_llm|\\.invoke\\(" src/harness/graph.py src/memory/retrieval_planner.py src/memory/context_assembler.py src/memory/retrieval_sources.py src/api/server.py
```

Read-only retrieval/observability scan:

```powershell
rg -n "INSERT|UPDATE|DELETE|commit\\(|enqueue_|create_version|create_approval_request|add_explicit_fact|record_used|reload_active_skills" src/memory/retrieval_planner.py src/memory/context_assembler.py src/memory/retrieval_sources.py src/memory/observability.py
```

Privacy scan:

```powershell
rg -n "api_key|secret|token|authorization|password|credential|chain_of_thought|scratchpad|reasoning" src/api/server.py src/memory/observability.py frontend/src
```
