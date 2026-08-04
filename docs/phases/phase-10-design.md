# Phase 10 Design: API and Frontend Observability

## 1. Executive Summary

Phase 10 adds safe backend, API, and frontend observability for the completed memory architecture without changing assistant behavior. The memory system now has durable jobs, worker state, immutable summaries, structured episodes, semantic candidates and consolidation, versioned procedural skills, skill promotion approvals, and adaptive retrieval. Operators need a coherent view of those subsystems without relying only on raw SQLite table inspection.

Phase 10 is observability-only:

- Add additive, backward-compatible API endpoints.
- Add curated, redacted views over existing memory tables and repositories.
- Add optional retrieval trace/debug APIs gated by an explicit debug request, never exposed through `/api/chat` by default.
- Add frontend panels for memory health, queue status, retrieval traces, semantic pipeline status, procedural pipeline status, skill versions, reload status, and usage stats.
- Do not change chat behavior, retrieval behavior, memory write logic, workers, schema, or existing endpoint response shapes.

Primary implementation targets:

- `src/api/server.py` for additive observability endpoints.
- Optional `src/memory/observability.py` for read-only helper functions and redaction.
- `frontend/src/components/MemoryCockpit.jsx` or a new `MemoryObservabilityCockpit.jsx` for operator panels.
- Optional `frontend/src/App.jsx` change only if adding a separate navigation tab.
- Tests for backend response shapes, privacy boundaries, read-only guarantees, and frontend compatibility.

## 2. Scope

In scope:

- Memory health/status API.
- Memory jobs observability API.
- Worker heartbeat and dead-letter visibility.
- Retrieval debug/trace API behind an explicit debug endpoint/flag.
- Semantic candidate and consolidation visibility.
- Procedural candidate, approval, and promotion visibility.
- Skill version, reload, and usage statistics visibility.
- Frontend observability panels that consume the additive APIs.
- Safe redaction of payloads, prompts, tokens, secrets, and large content.
- Tests for API shape and frontend compatibility.

Expected backend files:

- Modify: `src/api/server.py`
- Optional new: `src/memory/observability.py`
- Tests only.

Expected frontend files:

- Preferred new: `frontend/src/components/MemoryObservabilityCockpit.jsx`
- Optional modify: `frontend/src/App.jsx` to add a sidebar tab.
- Optional modify: `frontend/src/components/MemoryCockpit.jsx` if observability is added as memory subtabs instead.
- Optional modify: `frontend/src/styles/main.css` only for reusable table/status styles.

## 3. Out of Scope

Phase 10 must not implement:

- Chat behavior changes.
- Retrieval behavior changes.
- Memory write logic changes.
- New autonomous jobs.
- Worker auto-start.
- Public debug metadata exposure in `/api/chat` by default.
- Raw prompts or hidden chain-of-thought exposure.
- Secret/API key/provider credential exposure.
- Schema migrations unless an implementation blocker proves they are absolutely necessary.
- Frontend controls that mutate memory state beyond existing explicit admin actions.
- Candidate approval or promotion logic changes.
- New skill generation or retrieval ranking behavior.
- Backend behavior hidden behind frontend-only state.

Phase 10 may add new `GET` endpoints and an explicit read-only `POST /api/memory/observability/retrieval/trace` because retrieval tracing naturally needs a request body.

## 4. Current Observability Assessment

### Backend API

Current `src/api/server.py` provides:

- `/api/health`
- `/api/models`
- `/api/chat`
- `/api/memory`
- `/api/memory/full`
- `/api/skills`
- `/api/approvals`
- `/api/data/tables`
- `/api/data/table/{table_name}`

Strengths:

- Existing endpoints are stable and tested.
- `ALLOWED_DATA_TABLES` already includes Phase 2 memory tables, including `memory_jobs`, `dead_letter_jobs`, `worker_heartbeats`, `summary_blocks`, `structured_episodes`, `pending_fact_candidates`, `semantic_embeddings`, `semantic_dedup_events`, `consolidation_runs`, `skill_candidates`, `skill_versions`, `skill_usage_stats`, and `procedural_skill_approvals`.
- `/api/approvals/{request_id}/decision` already integrates procedural skill approval finalization.

Gaps:

- Operators must inspect raw tables to understand memory health.
- Raw data inspector is not designed as a privacy-safe operational dashboard.
- No curated queue summary, heartbeat age, dead-letter summary, or job payload redaction.
- No retrieval trace endpoint for explaining planner decisions outside of chat.
- No single semantic candidate/consolidation status view.
- No single procedural candidate/promotion/skill version lifecycle view.

### Graph and Retrieval

Current Phase 9B retrieval path:

```text
node_retrieval_gate()
  -> should_retrieve_memory()
  -> build_retrieval_plan()
  -> retrieve_all_sources()
  -> assemble_retrieved_memory_context()
  -> append one [Retrieved Long-Term Memory] SystemMessage
```

Observability gap:

- The planner and assembler have internal debug metadata, but it is intentionally not exposed by `/api/chat`.
- Operators need an explicit, separate trace endpoint to inspect planning and context assembly decisions safely.

### Frontend

Current frontend tabs:

- Overview
- Chat
- Loop Timeline
- Task & Sub-Agents
- Memory
- Approvals
- Tools Catalog
- Scheduled Jobs
- Data Inspector

`MemoryCockpit.jsx` shows `/api/memory/full` facts, legacy episodes, `SOUL.md`, `SKILL.md`, and `MEMORY.md`. `DataCockpit.jsx` shows raw allow-listed tables.

Gaps:

- No curated memory health dashboard.
- No queue/worker/dead-letter panels.
- No semantic/procedural pipeline progress panels.
- No retrieval trace form.
- No skill version/reload/usage overview.

## 5. Backend API Design

Add endpoints under `/api/memory/observability/*` to avoid changing existing endpoint response shapes.

Recommended endpoints:

| Endpoint | Method | Purpose | Writes |
| --- | --- | --- | --- |
| `/api/memory/observability/health` | `GET` | Overall memory architecture health/status summary. | No |
| `/api/memory/observability/jobs` | `GET` | Queue status summary and recent jobs. | No |
| `/api/memory/observability/workers` | `GET` | Worker heartbeat summary and stale worker indicators. | No |
| `/api/memory/observability/dead-letter` | `GET` | Dead-letter count and recent redacted failures. | No |
| `/api/memory/observability/retrieval/trace` | `POST` | Explicit debug retrieval trace for a query/session. | No |
| `/api/memory/observability/semantic` | `GET` | Semantic candidates, dedup, consolidation status. | No |
| `/api/memory/observability/procedural` | `GET` | Skill candidates, approvals, promotions. | No |
| `/api/memory/observability/skills` | `GET` | Versioned skill, reload, and usage status. | No |
| `/api/memory/observability/overview` | `GET` | Aggregated dashboard summary for frontend. | No |

Implementation pattern:

- Keep route handlers thin.
- Prefer read-only SQL or existing read-only repository helpers.
- If route code becomes bulky, add `src/memory/observability.py` with read-only helpers.
- Never call worker mutating methods such as `claim_next_due_job()`, `handle_job_failure()`, `recover_stale_running_jobs()`, or `upsert_worker_heartbeat()`.
- Never call candidate claim/update helpers.
- Never call `SkillRuntimeReloader.reload_active_skills()` from observability endpoints because reload increments usage stats.

## 6. Memory Health Endpoint Design

Endpoint:

```text
GET /api/memory/observability/health
```

Purpose:

- Provide an operator-safe, high-level status snapshot.
- Confirm required memory tables exist.
- Surface stale workers, dead letters, failed jobs, pending candidates, and skill approval backlog.

Response shape:

```json
{
  "status": "OK",
  "generated_at": "2026-08-04T00:00:00Z",
  "schema": {
    "required_tables_present": true,
    "missing_tables": [],
    "migration_version": 8
  },
  "queue": {
    "total_jobs": 0,
    "by_status": {},
    "oldest_queued_at": null,
    "dead_letter_count": 0
  },
  "workers": {
    "total_workers": 0,
    "active_workers": 0,
    "stale_workers": 0,
    "last_heartbeat_at": null
  },
  "semantic": {
    "pending_candidates": 0,
    "in_consolidation": 0,
    "failed_candidates": 0,
    "recent_consolidation_status": null
  },
  "procedural": {
    "new_candidates": 0,
    "ready_for_promotion": 0,
    "waiting_for_approval": 0,
    "promoted": 0,
    "rejected": 0
  },
  "skills": {
    "active_versions": 0,
    "disabled_versions": 0,
    "total_times_loaded": 0,
    "total_times_used": 0
  }
}
```

Status calculation:

- `OK`: required tables present, no stale running jobs, no dead-letter backlog, no recent worker errors.
- `DEGRADED`: retry backlog, dead-letter rows, stale heartbeat, failed candidates, or pending approval backlog.
- `ERROR`: missing required tables or database read failure.

The endpoint must not include raw job payloads, raw prompts, raw candidate rationale, or secrets.

## 7. Job Queue / Worker Observability

### Jobs Endpoint

Endpoint:

```text
GET /api/memory/observability/jobs?session_id=&status=&job_type=&limit=50&include_payload=false
```

Response shape:

```json
{
  "summary": {
    "total": 12,
    "by_status": {"QUEUED": 2, "SUCCEEDED": 10},
    "by_type": {"semantic_candidate_extraction": 4},
    "oldest_queued_at": "...",
    "newest_created_at": "..."
  },
  "jobs": [
    {
      "id": "job_...",
      "job_type": "semantic_candidate_extraction",
      "status": "QUEUED",
      "priority": 100,
      "session_id": "session_...",
      "attempt_count": 0,
      "max_attempts": 3,
      "available_at": "...",
      "locked_by": null,
      "locked_at": null,
      "last_error": null,
      "created_at": "...",
      "updated_at": "...",
      "payload": null,
      "payload_redacted": true
    }
  ]
}
```

Rules:

- Limit must be clamped, recommended range `1..200`.
- `include_payload=false` by default.
- If `include_payload=true`, return redacted payload only.
- Redact message text, raw turns, prompts, provider secrets, candidate rationale, and hidden metadata.
- Keep structural metadata such as job type, schema version, source IDs, turn counts, and model selector names.

### Workers Endpoint

Endpoint:

```text
GET /api/memory/observability/workers?stale_after_seconds=120
```

Response shape:

```json
{
  "summary": {
    "total": 1,
    "active": 1,
    "stale": 0,
    "last_heartbeat_at": "..."
  },
  "workers": [
    {
      "worker_id": "memory-worker-1",
      "status": "IDLE",
      "current_job_id": null,
      "last_heartbeat_at": "...",
      "age_seconds": 8,
      "stale": false,
      "metadata": {
        "worker_type": "memory",
        "phase": "3B",
        "worker_version": 1
      }
    }
  ]
}
```

Hostname/pid redaction:

- Include `worker_type`, `phase`, and `worker_version` by default.
- Redact or omit hostname and pid unless an explicit `include_host_metadata=true` flag is supplied.

### Dead Letter Endpoint

Endpoint:

```text
GET /api/memory/observability/dead-letter?limit=50&include_details=false
```

Response shape:

```json
{
  "summary": {
    "total": 0,
    "by_job_type": {},
    "newest_created_at": null
  },
  "dead_letters": [
    {
      "id": "dlj_...",
      "job_id": "job_...",
      "job_type": "semantic_consolidation",
      "session_id": "session_...",
      "error_message": "redacted summary",
      "attempt_count": 3,
      "created_at": "...",
      "details": null,
      "details_redacted": true
    }
  ]
}
```

Rules:

- Details are redacted by default.
- Never expose raw prompts or full payloads.
- Error messages should be truncated and secret-scanned.

## 8. Retrieval Trace Observability

Endpoint:

```text
POST /api/memory/observability/retrieval/trace
```

Request shape:

```json
{
  "query": "what did we decide about deployment?",
  "session_id": "session_123",
  "provider": "openai",
  "model_name": "gpt-4o-mini",
  "include_candidates": true,
  "include_prompt_block": false,
  "max_candidates": 20
}
```

Purpose:

- Explain what Phase 9B would retrieve for a query without creating a chat turn.
- Inspect retrieval gate decision, planner task type, memory kinds, token allocations, source errors, included/omitted candidate IDs, and redacted candidate summaries.

Execution flow:

1. Use `should_retrieve_memory(query)` for the gate decision.
2. Build a minimal message list with one `HumanMessage(content=query)` for budget diagnostics.
3. Call `build_retrieval_plan(..., include_debug=True)`.
4. If plan says no retrieval, return the plan summary with no bundle.
5. Call `retrieve_all_sources(plan.retrieval_request)`.
6. Call `assemble_retrieved_memory_context(..., include_debug=True)`.
7. Return redacted metadata.

Response shape:

```json
{
  "query": "what did we decide about deployment?",
  "session_id": "session_123",
  "gate": {
    "allowed": true,
    "reason": "ok"
  },
  "plan": {
    "task_type": "episodic_recall",
    "memory_kinds": ["episodic", "summary", "semantic"],
    "per_source_limit": 5,
    "total_token_budget": 1024,
    "budget_by_kind": {"episodic": 563, "summary": 256, "semantic": 205}
  },
  "retrieval": {
    "source_results": [
      {
        "source_name": "structured_episodes",
        "memory_kind": "episodic",
        "candidate_count": 2,
        "errors": []
      }
    ],
    "candidate_count": 3,
    "omitted_candidate_ids": []
  },
  "assembly": {
    "included_candidate_ids": ["episodic:episode_1"],
    "omitted_candidate_ids": [],
    "token_count": 120,
    "prompt_block": null
  },
  "candidates": [
    {
      "id": "episodic:episode_1",
      "memory_kind": "episodic",
      "title": "Deployment decision",
      "content_preview": "We decided to run smoke tests...",
      "score": {
        "rank_score": 0.92,
        "strategy": "structured_episode_lexical"
      },
      "provenance": {
        "source_name": "structured_episodes",
        "table_name": "structured_episodes",
        "record_id": "episode_1",
        "created_at": "...",
        "fields_matched": ["summary", "topics"]
      }
    }
  ]
}
```

Privacy rules:

- `include_prompt_block=false` by default.
- If `include_prompt_block=true`, return the assembled memory block only after redaction and only from this explicit debug endpoint, not `/api/chat`.
- Candidate `content_preview` should be truncated, e.g. 240 characters.
- Do not include full provenance metadata if it contains raw payloads, source turn text, prompts, rationale, or hidden metadata.
- Do not expose planner/assembler `debug` dictionaries raw; convert them into known allow-listed fields.

## 9. Semantic Memory Observability

Endpoint:

```text
GET /api/memory/observability/semantic?session_id=&status=&limit=100
```

Purpose:

- Show pending fact candidate backlog and consolidation state.
- Show dedup event counts without exposing full private facts unless already permanent and visible through existing memory APIs.

Response shape:

```json
{
  "summary": {
    "pending_candidates": 0,
    "in_consolidation": 0,
    "promoted": 0,
    "discarded": 0,
    "deferred": 0,
    "failed": 0,
    "dedup_events": 0,
    "consolidation_runs": 0
  },
  "candidates": [
    {
      "id": "factcand_...",
      "session_id": "session_...",
      "status": "PENDING",
      "source": "semantic_candidate_extraction",
      "fact_preview": "User prefers...",
      "category": "preference",
      "confidence": 0.83,
      "source_job_id": "job_...",
      "created_at": "...",
      "updated_at": "..."
    }
  ],
  "recent_consolidation_runs": [
    {
      "id": "consolidation_...",
      "status": "SUCCEEDED",
      "source_job_id": "job_...",
      "candidate_count": 20,
      "promoted_count": 3,
      "discarded_count": 10,
      "deferred_count": 7,
      "created_at": "...",
      "updated_at": "..."
    }
  ],
  "recent_dedup_events": [
    {
      "id": "dedup_...",
      "action": "UPDATE",
      "target_fact_id": "12",
      "candidate_id": "factcand_...",
      "created_at": "..."
    }
  ]
}
```

Read sources:

- `pending_fact_candidates`
- `semantic_dedup_events`
- `consolidation_runs`
- Optional `facts` counts for permanent facts.

Rules:

- Do not call candidate claim/update helpers.
- Do not call semantic consolidation service methods that can mutate state.
- Do not call `SemanticFactStore.add_explicit_fact()`.
- Do not include raw LLM outputs or full candidate rationale by default.
- Use previews and status metrics for operator diagnostics.

## 10. Procedural Memory Observability

Endpoint:

```text
GET /api/memory/observability/procedural?status=&limit=100
```

Purpose:

- Show skill candidate lifecycle, dedup groups, promotion readiness, and approval linkage.

Response shape:

```json
{
  "summary": {
    "new": 0,
    "duplicate": 0,
    "updated": 0,
    "merged": 0,
    "ready_for_promotion": 0,
    "waiting_for_approval": 0,
    "promoted": 0,
    "rejected": 0
  },
  "candidates": [
    {
      "id": "skillcand_...",
      "title": "Deploy Staging",
      "status": "READY_FOR_PROMOTION",
      "workflow_category": "deployment",
      "confidence": 0.91,
      "occurrences": 3,
      "preferred_tools": ["shell"],
      "tags": ["deployment"],
      "dedup_group_id": "group_...",
      "source_episode_ids": ["episode_..."],
      "created_at": "...",
      "updated_at": "..."
    }
  ],
  "approvals": [
    {
      "id": "psa_...",
      "candidate_id": "skillcand_...",
      "approval_request_id": "approval_...",
      "status": "PENDING",
      "skill_version_id": null,
      "created_at": "...",
      "updated_at": "..."
    }
  ]
}
```

Read sources:

- `skill_candidates`
- `procedural_skill_approvals`
- Optional `approval_requests` for approval display status.

Rules:

- Do not call `select_candidates_for_skill_promotion()` if implementation might enqueue or mutate; use direct read-only queries or list helpers that are read-only.
- Do not write `skill_versions`.
- Do not create approval requests.
- Do not call skill promotion worker handler.

## 11. Skill Version / Reload Observability

Endpoint:

```text
GET /api/memory/observability/skills?include_archived=false
```

Purpose:

- Show active versioned skills, disabled/archived versions, loaded/used counters, and reload snapshot status.

Response shape:

```json
{
  "summary": {
    "active_versions": 0,
    "disabled_versions": 0,
    "archived_versions": 0,
    "total_times_loaded": 0,
    "total_times_used": 0,
    "snapshot_loaded_at": null,
    "snapshot_skill_count": 0
  },
  "active_versions": [
    {
      "id": "skillver_deploy-staging_v0001",
      "skill_id": "deploy-staging",
      "version": 1,
      "name": "Deploy Staging",
      "description": "Deploys the app to staging.",
      "enabled": true,
      "active": true,
      "author": "generated",
      "approval_required": true,
      "approval_id": "approval_...",
      "candidate_id": "skillcand_...",
      "confidence": 0.91,
      "file_path": ".agent/skills/generated/deploy-staging/v0001/SKILL.md",
      "content_hash": "sha256...",
      "created_at": "...",
      "approved_at": "...",
      "usage": {
        "times_loaded": 1,
        "times_used": 0,
        "last_loaded": "...",
        "last_used": null
      }
    }
  ],
  "snapshot": {
    "loaded_at": null,
    "skill_count": 0,
    "last_error": null
  }
}
```

Rules:

- Do not call `SkillRuntimeReloader.reload_active_skills()` because it records `times_loaded` and can change state.
- Do not call `record_skill_used()` or `SkillVersionStore.record_used()`.
- If a process-local `SkillRuntimeReloader` snapshot is not globally available, report `snapshot_loaded_at: null` and `snapshot_skill_count: 0` rather than triggering reload.
- File paths should be relative to the workspace or generated skill root where possible. Do not expose arbitrary absolute user paths unless already present and operator-safe.

## 12. Frontend Observability Design

Preferred approach:

- Add a new component: `frontend/src/components/MemoryObservabilityCockpit.jsx`.
- Add a new sidebar tab in `frontend/src/App.jsx` named `Memory Ops` or add an `ops` subtab under existing `MemoryCockpit.jsx`.
- Keep UI observability-only: refresh, filter, inspect redacted details. No mutation controls.

Recommended panels:

1. Health Overview
   - Status badge: `OK`, `DEGRADED`, `ERROR`.
   - Queue counts by status.
   - Worker heartbeat age.
   - Dead-letter count.
   - Pending semantic/procedural candidate counts.
   - Active skill version count.

2. Queue and Workers
   - Job table with filters for status, job type, session ID.
   - Worker heartbeat table.
   - Dead-letter table with redacted error summary.

3. Retrieval Trace
   - Query input, session ID input, provider/model optional inputs.
   - Trace button calls `/api/memory/observability/retrieval/trace`.
   - Shows gate decision, task type, memory kinds, token allocation, source counts, included/omitted candidates.
   - Prompt block hidden by default behind an explicit local toggle if the API request includes `include_prompt_block=true`.

4. Semantic Pipeline
   - Candidate status counts.
   - Candidate table with previews.
   - Recent consolidation runs.
   - Recent dedup events.

5. Procedural Pipeline
   - Candidate status counts.
   - Ready/waiting/promoted/rejected tables.
   - Approval linkage status.

6. Skill Versions
   - Active versions table.
   - Disabled/archived counts.
   - Usage counters.
   - Snapshot status without triggering reload.

Frontend design constraints:

- Use existing visual style and layout conventions.
- Keep operational UI dense and scannable, not marketing-like.
- Do not expose raw prompts or secrets.
- Do not add write controls in Phase 10.
- Handle empty states cleanly.
- Treat API failures as panel-local errors, not app-wide crashes.

## 13. Privacy / Redaction Rules

Create shared backend redaction helpers if implementing `src/memory/observability.py`:

```python
SENSITIVE_KEY_PATTERNS = (
    "api_key", "apikey", "token", "secret", "password", "credential",
    "authorization", "provider_key", "access_token", "refresh_token",
)

CONTENT_KEY_PATTERNS = (
    "prompt", "raw_turn", "raw_turns", "messages", "message_text",
    "conversation", "rationale", "llm_output", "candidate_text",
)
```

Rules:

- Replace sensitive scalar values with `[REDACTED]`.
- Replace raw text fields with previews unless endpoint explicitly allows redacted content preview.
- Truncate previews to a fixed length, e.g. 240 characters.
- Preserve counts, IDs, statuses, timestamps, and structural metadata.
- Never expose hidden chain-of-thought. The system should not store chain-of-thought, but redaction must still block keys such as `reasoning`, `chain_of_thought`, or `scratchpad` if present in payloads.
- Do not expose provider credentials from environment variables or model config.
- Do not expose full model prompts from job handlers.

Recommended helper functions:

```python
def redact_observability_value(key: str, value: Any, *, include_preview: bool = True) -> Any:
    ...

def redact_observability_payload(payload: Any, *, include_preview: bool = True) -> Any:
    ...

def safe_json_loads(value: str | None, default: Any) -> Any:
    ...

def truncate_preview(text: str, limit: int = 240) -> str:
    ...
```

## 14. Error Handling

Backend:

- Observability endpoints should return HTTP 500 only for unexpected database/API failures.
- Invalid filters should return HTTP 400 with a clear message.
- Limit parameters should be clamped rather than allowed to create huge responses.
- Partial subsystem failures in overview should return `status: DEGRADED` with a `errors` array rather than failing the whole endpoint when possible.
- Retrieval trace endpoint should return a valid trace with `gate.allowed=false` rather than erroring for empty/no-retrieval queries.

Frontend:

- Each panel has local loading/error state.
- A failing panel should not blank the full Memory Ops view.
- Empty states should say what is empty and why it is expected, e.g. no worker heartbeat because worker is not auto-started.

## 15. API Compatibility

Existing endpoints must keep response shapes:

- `/api/chat`
- `/api/memory`
- `/api/memory/full`
- `/api/skills`
- `/api/approvals`
- `/api/data/tables`
- `/api/data/table/{table_name}`
- `/api/models`

Additive endpoint guarantees:

- New observability endpoints live under `/api/memory/observability/*`.
- Existing data inspector allow-list remains valid.
- `/api/chat` does not expose planner debug metadata, source errors, candidate scores, or assembled prompt block beyond existing `retrieved_memories` behavior.
- Retrieval trace is explicit and separate.

## 16. Test Plan

### Backend API Tests

Suggested file: `tests/test_phase10_memory_observability_api.py`

Test cases:

- `/api/memory/observability/health` returns expected top-level keys.
- Health endpoint reports required tables present on fresh DB.
- Health endpoint returns `DEGRADED` when dead-letter rows exist.
- Jobs endpoint returns status/type summaries.
- Jobs endpoint redacts payload by default.
- Jobs endpoint with `include_payload=true` returns redacted payload, not raw text/secrets.
- Workers endpoint reports no workers without failing.
- Workers endpoint computes stale heartbeat status.
- Dead-letter endpoint redacts details by default.
- Semantic endpoint reports pending candidates and consolidation run counts.
- Procedural endpoint reports candidate and approval counts.
- Skills endpoint reports active versions and usage stats without calling reload or record-used methods.

### Retrieval Trace Tests

Suggested file: `tests/test_phase10_retrieval_trace_api.py`

Test cases:

- Trace endpoint requires non-empty query.
- Greeting/math trace reports gate skipped.
- Trace endpoint returns planner task type and memory kinds.
- Trace endpoint returns source result counts.
- Trace endpoint does not expose prompt block by default.
- `include_prompt_block=true` returns redacted assembled block only.
- Trace endpoint does not call LLMs.
- Trace endpoint does not write embeddings, dedup events, usage stats, memory jobs, candidates, or raw turns.
- Trace endpoint handles source failure as redacted source error.

### Privacy Tests

Suggested file: `tests/test_phase10_observability_redaction.py`

Test cases:

- Redacts keys containing `api_key`, `token`, `secret`, `password`, and `authorization`.
- Redacts nested payloads.
- Truncates raw message/prompt/candidate text previews.
- Does not include hidden reasoning/scratchpad fields.
- Keeps safe structural fields such as IDs, statuses, timestamps, counts, schema versions.

### Frontend Tests

Suggested files:

- `tests/test_phase10_frontend_observability.py`
- Existing frontend smoke tests may be extended if the project already uses static/import checks.

Test cases:

- New observability component file exists and exports a component.
- App renders existing tabs and new Memory Ops tab if added.
- Component fetches new observability endpoints.
- Empty API responses render empty states.
- Error states render without crashing.
- No write endpoints are called by frontend observability component.

### Regression Tests

Run:

```powershell
python -m pytest tests/test_api_server.py tests/test_frontend_api.py tests/test_p2_frontend_smoke.py tests/test_p3_frontend.py -q
python -m pytest tests/test_phase9a_retrieval_types.py tests/test_phase9a_retrieval_ranker.py tests/test_phase9b_retrieval_planner.py tests/test_phase9b_context_assembler.py tests/test_phase9b_graph_retrieval_integration.py -q
python -m pytest -q
```

## 17. Risks

Risk: Observability endpoints expose sensitive payload content.

Mitigation:

- Redact by default.
- Use allow-listed response fields.
- Add tests for nested secrets, prompts, raw turns, and hidden reasoning keys.

Risk: Observability accidentally mutates runtime state.

Mitigation:

- Use direct read-only SQL or known read-only repository helpers.
- Monkeypatch mutating methods in tests to raise if called.
- Avoid `reload_active_skills()`, `record_used()`, worker claim/recovery methods, and candidate claim/update helpers.

Risk: Retrieval trace changes retrieval behavior.

Mitigation:

- Trace uses the same read-only planner/retriever/assembler functions but does not connect to chat graph state or log raw turns.
- Do not add trace fields to `/api/chat`.

Risk: Frontend adds operational clutter or brittle panels.

Mitigation:

- Keep panels compact and table-driven.
- Add local error/empty states.
- Prefer one Memory Ops tab over spreading diagnostics across many existing components.

Risk: Existing endpoint response shapes drift.

Mitigation:

- Add explicit regression tests for `/api/chat`, `/api/memory`, `/api/memory/full`, `/api/skills`, `/api/approvals`, and `/api/data/*`.

## 18. Acceptance Criteria

Phase 10 is accepted when:

- Additive memory observability API endpoints exist under `/api/memory/observability/*`.
- Health endpoint summarizes schema, queue, workers, semantic pipeline, procedural pipeline, and skill state.
- Jobs, workers, and dead-letter endpoints expose redacted operational state.
- Retrieval trace endpoint is explicit, read-only, deterministic, and privacy-safe.
- Semantic observability shows candidate/consolidation/dedup status without mutating candidates or facts.
- Procedural observability shows candidate/approval/promotion status without creating approvals or skills.
- Skills observability shows version/usage/snapshot status without reload or usage increments.
- Frontend shows observability panels and handles empty/error states.
- Existing endpoints keep response shapes.
- `/api/chat` does not expose debug metadata by default.
- No chat behavior, retrieval behavior, worker behavior, schema, or memory write logic changes.
- Tests prove redaction and read-only behavior.
- Full test suite passes or any unrelated failure is documented.

## 19. Implementation Checklist

1. Decide whether to create `src/memory/observability.py` for read-only helpers.
2. Add redaction helpers and tests.
3. Add health summary helper.
4. Add jobs summary/list helper.
5. Add workers summary helper.
6. Add dead-letter summary/list helper.
7. Add retrieval trace helper using Phase 9B planner/retriever/assembler.
8. Add semantic observability helper.
9. Add procedural observability helper.
10. Add skills observability helper.
11. Add additive routes in `src/api/server.py`.
12. Add backend API tests.
13. Add retrieval trace tests.
14. Add privacy/redaction tests.
15. Add frontend Memory Ops component or MemoryCockpit subtabs.
16. Wire frontend route/tab if needed.
17. Add frontend smoke tests.
18. Run focused Phase 10 tests.
19. Run Phase 9 retrieval regressions.
20. Run API/frontend regressions.
21. Run full suite.
22. Perform filesystem wiring check.

## 20. Filesystem Wiring Check Required After Implementation

Before final implementation approval, verify actual filesystem state, not only the UI edited-files list.

Required checks:

- Verify `src/api/server.py` changed only by adding observability routes and request/response helper models if needed.
- Verify optional `src/memory/observability.py` contains only read-only helpers and redaction utilities.
- Verify `src/harness/graph.py` was not modified.
- Verify retrieval modules were not modified unless a documented bug fix was required.
- Verify memory store modules were not modified unless a read-only list helper was absolutely necessary.
- Verify worker/job execution modules were not modified.
- Verify schema/migration files were not modified.
- Verify frontend changes are observability-only.
- Verify `/api/chat` response shape is unchanged.
- Verify no worker auto-start was added.
- Verify no new autonomous jobs were added.
- Verify no raw prompts, hidden reasoning, secrets, API keys, or provider credentials are exposed.

Suggested static scans:

```powershell
git status --short
rg -n "claim_next_due_job|handle_job_failure|recover_stale_running_jobs|upsert_worker_heartbeat|reload_active_skills|record_skill_used|record_used|create_approval_request|create_version|enqueue_|add_explicit_fact|INSERT|UPDATE|DELETE|commit\(" src/api/server.py src/memory/observability.py
rg -n "api_key|secret|token|authorization|password|credential" src/api/server.py src/memory/observability.py frontend/src
```

Expected result:

- Static scan may find existing API write endpoints in `src/api/server.py`; confirm no new observability route calls mutating functions.
- New observability helper, if created, should have no SQL writes and no mutating repository calls.
- Frontend should call only new `GET` endpoints and explicit read-only retrieval trace endpoint.
