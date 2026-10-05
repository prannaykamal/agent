# Memory Failure Recovery

## Queue Retry And Dead Letter

Worker handlers return success, retryable failure, or terminal failure. Retryable failures move jobs to `RETRYING` with deterministic backoff. Exhausted jobs move to `dead_letter_jobs` and mark the original job `DEAD_LETTERED`.

Recovery:

1. Inspect `/api/memory/observability/dead-letter`.
2. Fix credentials, payload validation bug, or handler issue.
3. Keep manual DB requeue as a backed-up maintenance action only.

## Stale Worker Recovery

If a worker crashes, a job can remain `RUNNING`.

Recovery:

```powershell
python -c "from src.memory.worker import recover_stale_running_jobs; print(recover_stale_running_jobs(worker_id='recovery-operator'))"
```

## cognee Not Installed Or Disabled

Expected behavior:

- Chat still works. Recall returns nothing, so no `[Retrieved Long-Term Memory]` block is injected.
- Memory health reports `DEGRADED`, and `/api/memory/observability/long-term` shows `available: false` with the reason.
- `memory_session_write`, `memory_session_merge`, and `cognee_ingest` jobs fail as non-retryable and go straight to dead letters, so they are not retried forever.

Recovery:

1. Install cognee (`pip install -r requirements.txt`) or set `COGNEE_ENABLED=true`.
2. Restart the API. The import result is cached per process, so a running process will not notice a fresh install.
3. Re-queue lost knowledge: turns from the outage are in `raw_turns` but were not ingested. Run the legacy backfill for older data; re-ingesting outage turns is a manual, backed-up maintenance action.

## cognee Provider Outage (LLM Or Embeddings)

Expected behavior:

- Chat still works without long-term context. Recall failures are logged, and the timeout (`MEMORY_COGNEE_RECALL_TIMEOUT_SECONDS`) bounds the added latency.
- Session writes, merges, and `cognee_ingest` jobs retry with backoff, then dead-letter.

Recovery:

1. Fix the key for the active `AI_PROVIDER` (`GOOGLE_API_KEY` for gemini, `OPENAI_API_KEY` for openai); cognee uses that provider's models and key.
2. Restart the API.
3. Force-merge sessions whose merges dead-lettered: `POST /api/memory/sessions/<session_id>/merge`.
4. Check `/api/memory/observability/long-term` for new `SUCCEEDED` merges.

## Chat Model Overloaded Or Out Of Quota (Gemini Free Tier)

Expected behavior:

- The turn completes with an offline message that includes the provider error, for example `503 UNAVAILABLE` or `RESOURCE_EXHAUSTED`. Memory routing and stored memory are unaffected.

Recovery:

1. Resend the message after a short wait; `503` is usually transient.
2. `RESOURCE_EXHAUSTED` means a rate or daily quota was hit. Wait for the quota to reset, use a lighter model (`PRIMARY_MODEL=gemini-3.5-flash`), or switch to a paid tier.

## Jev Unavailable Or Misbehaving

Expected behavior:

- Chat still works. `memory.store.decision` and `memory.retrieve.decision` logs show `source: fallback` with an `error_category`.
- Fallback decisions: nothing is stored from chat, retrieval runs for every non-trivial message, and tool calls follow policy alone (no escalation).

Recovery:

1. Check `JEV_ENDPOINT`, `JEV_MODEL`, `JEV_API_KEY`, and that the endpoint answers OpenAI-style `POST /chat/completions`.
2. `ValidationError` or `JevError` categories mean the model is not returning the required JSON; use a model that follows instructions, or a server with JSON mode.
3. Raise `JEV_TIMEOUT_SECONDS` only if the model is slow but correct; every chat turn waits for the decision.

## Session Merge Stuck Or Failing

Merges retry when cognee reports `errored`, `running`, or a lock held by another run. Exhausted retries dead-letter.

Recovery:

1. Inspect `/api/memory/observability/dead-letter` for `memory_session_merge` jobs and the redacted error.
2. Fix the cause (usually cognee's LLM or embedding provider).
3. `POST /api/memory/sessions/<session_id>/merge`. Forced merges skip the idle check; a merge with nothing new is a no-op, so repeating it is safe.

## Embedding Dimension Mismatch

If a merge, explicit write, or search fails with a vector dimension error, the configured embedding model and `EMBEDDING_DIMENSIONS` disagree, or the model changed after data was stored.

Recovery:

1. Set `EMBEDDING_DIMENSIONS` to the model's real size.
2. If the embedding model changed, the stored vectors are incompatible: back up, reset long-term memory (`forget_all()`), and re-import with the backfill.

## Knowledge Not Showing Up In Recall

Chat knowledge is searchable only after its session merges into the main graph, which happens once the conversation has been idle for `SESSION_IDLE_TIMEOUT` minutes. Only messages Jev marked `should_store` are written at all.

Recovery:

1. Check that the `cognee_ingest` job for the turn `SUCCEEDED`.
1a. If there is no `memory_session_write` job for the turn, Jev decided not to store it (see `memory.store.decision` logs).
2. Check that a later `memory_session_merge` job `SUCCEEDED` with `merged: true`; if it was deferred, the conversation is still active. To merge now, `POST /api/memory/sessions/<session_id>/merge`.
3. Run a retrieval trace with the same query. Try `search_type: "CHUNKS"` to separate graph-extraction problems from storage problems.

## Secondary Outage

Expected behavior:

- Chat still works.
- `summary_generation` jobs retry or dead-letter.

Recovery:

1. Restore secondary provider credentials.
2. Confirm `/api/models` and memory config.
3. Run explicit worker step.
4. Inspect health and dead letters.

## Corrupt cognee Data Directory

Recovery:

1. Stop the API so the worker is not writing.
2. Restore the latest backup; it contains the cognee directory under `cognee/`.
3. If no backup exists, move `.agent/cognee` aside, restart, and re-import with the legacy backfill. Knowledge learned only from chat since the last backup is lost.

## DB Locked Or Unavailable

Expected behavior depends on path:

- Chat should not fail after a response has already been generated because a memory enqueue failed.
- Worker paths should retry or fail safely.
- Observability should report errors rather than mutate state.

Recovery:

1. Release the lock or restore DB availability.
2. Re-run migrations if startup was interrupted.
3. Run health endpoint.
4. Run focused DB and worker tests.
