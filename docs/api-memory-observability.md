# Memory Observability API

All endpoints under `/api/memory/observability/*` are additive and read-only. They must not mutate jobs, candidates, facts, episodes, skills, worker state, or retrieval state.

## Redaction Rules

Redacted keys include values containing:

- `api_key`
- `token`
- `secret`
- `password`
- `credential`
- `authorization`
- `chain_of_thought`
- `scratchpad`
- `reasoning`

Raw prompt, message, rationale, and conversation fields are returned as deterministic previews instead of full text.

## `GET /api/memory/observability/health`

Query parameters:

- `stale_after_seconds`: worker heartbeat stale threshold. Default: `120`.

Example response:

```json
{
  "status": "OK",
  "schema": {"required_tables_present": true, "missing_tables": []},
  "queue": {"total_jobs": 0, "dead_letter_count": 0},
  "workers": {"active_workers": 0, "stale_workers": 0},
  "semantic": {"pending_candidates": 0},
  "procedural": {"ready_for_promotion": 0},
  "skills": {"active_versions": 0}
}
```

## `GET /api/memory/observability/jobs`

Query parameters:

- `session_id`
- `status`
- `job_type`
- `limit`
- `include_payload`

Payloads are omitted by default. When included, payloads are redacted.

## `GET /api/memory/observability/workers`

Query parameters:

- `stale_after_seconds`
- `include_host_metadata`

Host and process metadata are hidden unless explicitly requested.

## `GET /api/memory/observability/dead-letter`

Query parameters:

- `limit`
- `include_details`

Details are omitted by default. Included details are redacted.

## `POST /api/memory/observability/retrieval/trace`

Request:

```json
{
  "query": "what do you remember about deployment?",
  "session_id": "default_session",
  "provider": "openai",
  "model_name": "gpt-4o-mini",
  "include_candidates": true,
  "include_prompt_block": false,
  "max_candidates": 20
}
```

Behavior:

- Requires non-empty `query`.
- Uses the retrieval gate, planner, sources, and assembler.
- Does not create chat turns.
- Does not write memory.
- Does not call LLMs.
- Hides prompt block by default.
- Redacts prompt block when explicitly included.

## `GET /api/memory/observability/semantic`

Query parameters:

- `session_id`
- `status`
- `limit`

Reads pending fact candidates, dedup events, consolidation runs, and permanent fact counts.

## `GET /api/memory/observability/procedural`

Query parameters:

- `status`
- `limit`

Reads skill candidates and procedural approval linkage. It does not create approvals or promote skills.

## `GET /api/memory/observability/skills`

Query parameters:

- `include_archived`

Reads skill versions and usage stats. It does not reload active skills or record usage.

## `GET /api/memory/observability/overview`

Combines the main health, queue, worker, semantic, procedural, and skill summaries for frontend Memory Ops.
