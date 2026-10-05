# Developer Testing Guide

## Full Suite

```powershell
python -m pytest -q
```

The suite runs offline by default: `tests/conftest.py` strips LLM API keys (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `XAI_API_KEY`), `LANGCHAIN_API_KEY`, the Jev endpoint, and messaging-provider tokens for every test and turns LangSmith tracing off, so keys in your local `.env` are never used. Chat-path tests that do not stub the LLM get the offline fallback reply.

The real-provider smoke tests in `tests/test_p7_product_readiness.py` make paid API calls. They, and any test that should see your real keys, run only when you opt in:

```bash
RUN_LIVE_PROVIDER_TESTS=1 python -m pytest tests/test_p7_product_readiness.py -k real_provider -q
```

## Phase 11 Focused Suite

```powershell
python -m pytest tests/test_phase11_e2e_chat_memory_pipeline.py tests/test_phase11_e2e_worker_lifecycle.py tests/test_phase11_e2e_observability_readonly.py tests/test_phase11_startup_config_validation.py tests/test_phase11_api_frontend_regression.py tests/test_phase11_architecture_wiring.py -q
```

## Core Regression Suites

Memory jobs and worker:

```powershell
python -m pytest tests/test_phase3a_memory_jobs.py tests/test_phase3a_graph_enqueue.py tests/test_phase3b_worker_repository.py tests/test_phase3b_worker_step.py tests/test_phase3b_router_handlers.py -q
```

Short-term memory, cognee long-term memory, retrieval, and observability:

```powershell
python -m pytest tests/test_phase5b_graph_short_term.py tests/test_phase5b_summary_job_handler.py tests/test_cognee_memory.py tests/test_jev_cognee_memory.py tests/test_e2e.py tests/test_phase10_memory_observability_api.py -q
```

`tests/test_e2e.py::test_e2e_conversation_is_remembered_through_cognee` covers the full loop: Jev decisions, chat recall, the worker's session write, the idle merge, and recall of the new turn. `tests/test_jev_cognee_memory.py` covers storage, idle merge, retrieval, context management, Jev tool review, failure handling, and session isolation.

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
- Temporary `SOUL.md`.

Use `monkeypatch` to patch:

- `src.db.DB_PATH`
- LLM router resolution helpers.

Do not use the real user `.agent` directory in tests. `tests/conftest.py` enforces the database part: the autouse `isolate_default_database` fixture points `src.db.DB_PATH` at a fresh temporary database for every test, so a test that forgets to patch it writes to a throwaway file instead of `.agent/state.db`. Tests that need a specific database still patch it themselves. The same conftest also clears `AI_PROVIDER` and the `JEV_*` settings, so a local `.env` cannot change test behaviour; tests that need a provider set it with `monkeypatch.setenv`.

## cognee In Tests

Tests never touch a real cognee install. `tests/conftest.py` provides:

- `isolate_cognee_memory` (autouse): installs a disabled `CogneeMemory`, so recall returns nothing and `cognee_*` jobs fail as "disabled".
- `fake_cognee`: installs `CogneeMemory` backed by `FakeCogneeModule`, an in-memory stand-in for cognee 1.x (`remember` with and without `session_id`, `improve`, `search`, `forget`, `SearchType`, `config`). Session entries only reach the searchable `graph` through `improve`. Set `improve_result` to simulate errored or lock-held merges. Inspect `sessions`, `graph`, `remember_calls`, `improve_calls`, and `search_calls`.
- `isolate_cognee_memory` also installs an unconfigured Jev, so no test can reach a real Jev endpoint.
- `fake_jev`: installs a configured Jev whose answers you control. Set `.memory` (`{"should_store", "should_retrieve"}`), `.tool` (`{"requires_approval", "reason"}`), `.raw` for malformed output, or `.fail = True` to simulate a timeout. Inspect `.calls`.
- Patch `src.memory.job_handlers._utcnow` to move the session-idle clock.

Seed knowledge through the real adapter so the loop thread and kwarg filtering are exercised:

```python
get_cognee_memory().remember_permanent(["Fact about the user (profile): prefers pytest"])
```

## Provider Switch And Gemini Content

- `tests/test_ai_provider_switch.py` covers `AI_PROVIDER` defaults, explicit overrides, model/provider pairing, chat API defaults, retired Gemini names, and Jev key selection.
- `tests/test_message_text.py` covers plain-text extraction from Gemini-style content blocks, including the chat API response and stored chat turns.

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
rg -n "resolve_secondary_llm|get_secondary_llm|\\.invoke\\(" src/harness/graph.py src/memory/cognee_memory.py src/api/server.py
```

Read-only retrieval/observability scan:

```powershell
rg -n "INSERT|UPDATE|DELETE|commit\\(|enqueue_|create_approval_request|\\.remember|\\.merge_session\\(" src/memory/observability.py
```

Privacy scan:

```powershell
rg -n "api_key|secret|token|authorization|password|credential|chain_of_thought|scratchpad|reasoning" src/api/server.py src/memory/observability.py frontend/src
```
