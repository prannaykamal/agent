# Memory Observability API

All endpoints under `/api/memory/observability/*` are additive and read-only. They must not mutate jobs, worker state, or the cognee knowledge graph, and they never call `cognee.remember` or `cognee.improve`.

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
  "long_term": {"backend": "cognee", "available": true, "dataset_name": "ivo_memory", "pipeline": {}}
}
```

`status` is `DEGRADED` when there are dead letters, stale workers, failed jobs, or cognee is unavailable (disabled, not installed, or failed to initialise).

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

## `GET /api/memory/observability/long-term`

Reports the cognee backend and its job pipeline. Checking availability may import cognee, but never writes or merges memory.

Example response:

```json
{
  "backend": "cognee",
  "enabled": true,
  "available": true,
  "error": null,
  "dataset_name": "ivo_memory",
  "search_type": "SUMMARIES",
  "storage_enabled": true,
  "retrieval_enabled": true,
  "user_id": "default_user",
  "session_idle_timeout_minutes": 30,
  "data_dir": ".agent/cognee",
  "version": "0.3.x",
  "jev": {"configured": true, "model": "jev-small", "tool_review_enabled": true},
  "pipeline": {
    "memory_session_write": {"by_status": {"SUCCEEDED": 12}, "last_succeeded_at": "2026-10-03 09:15:02"},
    "memory_session_merge": {"by_status": {"SUCCEEDED": 3, "QUEUED": 1}, "last_succeeded_at": "2026-10-03 08:44:40"},
    "cognee_ingest": {"by_status": {"SUCCEEDED": 1}, "last_succeeded_at": "2026-10-02 18:01:12"}
  }
}
```

`error` is truncated to 240 characters. The Jev endpoint URL and key are never returned, because URLs can embed credentials.

## `POST /api/memory/observability/retrieval/trace`

Request:

```json
{
  "query": "what do you remember about deployment?",
  "session_id": "default_session",
  "search_type": null,
  "include_candidates": true,
  "include_prompt_block": false,
  "max_candidates": 20
}
```

Behavior:

- Requires non-empty `query`. `search_type`, if given, must be `GRAPH_COMPLETION`, `RAG_COMPLETION`, `CHUNKS`, or `SUMMARIES`.
- Runs the rule gate and the same main-graph recall the chat path uses. It does not call Jev, so it shows what *would* be recalled if Jev asked for retrieval.
- Does not create chat turns.
- Does not write memory or enqueue jobs.
- Does not call a completion LLM (cognee is asked for context only). The query is embedded.
- Hides the prompt block by default and redacts it when explicitly included.

Example response:

```json
{
  "query": "what do you remember about deployment?",
  "gate": {"allowed": true},
  "backend": "cognee",
  "search_type": "SUMMARIES",
  "available": true,
  "error": null,
  "candidate_count": 1,
  "token_count": 24,
  "prompt_block": null,
  "candidates": [{"rank": 1, "content_preview": "User prefers pytest smoke checks before deploys."}]
}
```

## `GET /api/memory/observability/overview`

Combines the health, queue, worker, and long-term summaries for frontend Memory Ops.

## Related Memory Endpoints (not observability)

These live outside `/observability` because they write or query memory:

| Endpoint | Effect |
|---|---|
| `GET /api/memory` | cognee backend status |
| `GET /api/memory/full?query=` | Backend status, recall results for `query`, and `SOUL.md` |
| `POST /api/memory/search` | Main-graph recall with optional `search_type`, `top_k` (1–50) |
| `POST /api/memory/fact` | Queues a `cognee_ingest` job (straight to the main graph) |
| `POST /api/memory/procedure` | Queues a `cognee_ingest` job (straight to the main graph) |
| `POST /api/memory/sessions/{session_id}/merge` | Queues a forced `memory_session_merge`, skipping the idle wait |

Removed with the move to cognee: `/api/memory/observability/semantic`, `/api/memory/observability/semantic/consolidate`, `/api/memory/observability/procedural`, `/api/memory/observability/skills`, `/api/skills`, and `/api/memory/cognify`.
