# Operator Runbook

This runbook covers day-to-day operation of the memory architecture: short-term summaries plus a cognee knowledge graph for long-term memory. See [Memory Architecture](memory-architecture.md) for the design.

## Install

```powershell
pip install -r requirements.txt
```

`cognee` is a required dependency. If it is missing or `COGNEE_ENABLED=false`, chat still works but has no long-term memory, and memory health reports `DEGRADED`.

cognee may lag behind the newest Python release. If `pip install cognee` fails on your interpreter, create the virtualenv with a version cognee supports.

## Configure Long-Term Memory

The defaults work with only `OPENAI_API_KEY` set:

- cognee's `LLM_API_KEY` and `EMBEDDING_API_KEY` default to `OPENAI_API_KEY`.
- `EMBEDDING_DIMENSIONS` is set automatically for known OpenAI embedding models.
- Data is stored under `.agent/cognee`.

To use another provider for graph extraction or embeddings, set cognee's variables explicitly (`LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY`, `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`, `EMBEDDING_DIMENSIONS`). Explicit values are never overridden. The `MEMORY_COGNEE_*` settings are listed in `.env.example`.

## Configure Jev

Jev is the small routing model that decides, per message, whether to store and whether to retrieve long-term memory, and may escalate medium-risk tool calls to approval. Point it at any OpenAI-compatible chat endpoint:

```dotenv
JEV_ENDPOINT=http://localhost:8001/v1
JEV_MODEL=your-jev-model
JEV_API_KEY=...            # optional for local servers
JEV_TIMEOUT_SECONDS=5
```

Without Jev the assistant still works: nothing is stored from chat, retrieval runs for every non-trivial message, and tool calls follow policy alone. `GET /api/memory/observability/long-term` shows whether Jev is configured. Tune `SESSION_IDLE_TIMEOUT` (minutes) for how long a conversation must be quiet before its session merges into the main graph.

## Start The Backend

```powershell
python src/api/server.py
```

The server initializes directories and the SQLite schema through `ensure_system_initialized()`, then starts the in-process memory worker (`src/memory/worker_runtime.py`). Set `MEMORY_WORKER_AUTOSTART=false` to run the worker separately. The worker never starts under pytest.

## Start The Frontend

Development:

```powershell
Set-Location frontend
npm run dev
```

Production build:

```powershell
Set-Location frontend
npm run build
```

## Initialize The System

Initialization creates:

- `.agent`
- `.agent/scratch`
- `.agent/SOUL.md` when missing
- `.agent/cognee`
- SQLite tables and migrations

`MEMORY.md`, `SKILL.md`, and `.agent/skills` are no longer created or updated. Existing copies are left untouched.

## Run One Memory Worker Step

Use one-step execution for diagnosis:

```powershell
python -c "from src.memory.worker import process_one_memory_job; print(process_one_memory_job(worker_id='memory-worker-manual'))"
```

## Run The Explicit Memory Worker Loop

When `MEMORY_WORKER_AUTOSTART=false`:

```powershell
python -c "from src.memory.worker import run_memory_worker_loop; run_memory_worker_loop(worker_id='memory-worker-1')"
```

Chat and retrieval never run the worker.

## Check Memory Health

```powershell
curl http://localhost:8000/api/memory/observability/health
curl http://localhost:8000/api/memory/observability/long-term
```

Health summarizes schema, queue, workers, dead letters, and the cognee backend. `long-term` shows whether cognee is available, its dataset and search type, Jev status, and the status counts for `memory_session_write`, `memory_session_merge`, and `cognee_ingest` jobs.

## Inspect Jobs

```powershell
curl "http://localhost:8000/api/memory/observability/jobs?limit=50"
curl "http://localhost:8000/api/memory/observability/jobs?status=RETRYING"
curl "http://localhost:8000/api/memory/observability/jobs?job_type=memory_session_merge"
```

Payloads are hidden by default. If `include_payload=true` is used, payloads are still redacted.

## Inspect Workers

```powershell
curl "http://localhost:8000/api/memory/observability/workers?stale_after_seconds=120"
```

Stale workers indicate a worker heartbeat older than the configured threshold.

## Inspect Dead Letters

```powershell
curl "http://localhost:8000/api/memory/observability/dead-letter"
```

Dead-letter details are redacted. Use the job type, status, attempt count, and last error preview to decide whether a code or config fix is needed.

## Search Long-Term Memory

```powershell
curl -X POST http://localhost:8000/api/memory/search -H "Content-Type: application/json" -d "{\"query\":\"what do you remember about deployment?\"}"
```

Searches the main graph only; sessions appear after they merge. The Memory page's Recall tab uses this endpoint.

## Run Retrieval Trace

```powershell
curl -X POST http://localhost:8000/api/memory/observability/retrieval/trace -H "Content-Type: application/json" -d "{\"query\":\"what do you remember about deployment?\",\"session_id\":\"default_session\"}"
```

Retrieval trace runs exactly the recall the chat path uses. It does not create chat turns, enqueue jobs, write memory, or call a completion LLM. Prompt block output is hidden by default.

## Teach Memory Directly

```powershell
curl -X POST http://localhost:8000/api/memory/fact -H "Content-Type: application/json" -d "{\"category\":\"user_preference\",\"fact_text\":\"User prefers concise summaries.\"}"
curl -X POST http://localhost:8000/api/memory/procedure -H "Content-Type: application/json" -d "{\"name\":\"Inbox digest\",\"description\":\"Summarize unread mail\",\"trigger_keywords\":\"inbox, digest\",\"execution_steps\":\"1. Fetch unread 2. Extract actions 3. Bullet them\"}"
```

Both queue a `cognee_ingest` job that writes straight into the main graph, bypassing Jev and the session cache. The knowledge becomes searchable once the worker has processed it.

## Merge A Session Now

```powershell
curl -X POST http://localhost:8000/api/memory/sessions/<session_id>/merge
```

Queues a forced `memory_session_merge` for that conversation, skipping the idle wait. Use it for recovery after a dead-lettered merge, or when testing.

## Import Legacy Memory

Run once after upgrading from the semantic/episodic/procedural stores. See [Legacy Memory Backfill](legacy-memory-backfill.md).

```powershell
python -m src.memory.cognee_backfill --dry-run
python -m src.memory.cognee_backfill
```

## Backup And Restore

`POST /api/system/backup` (or the Overview page) archives:

- `state.db`
- `SOUL.md`, plus legacy `MEMORY.md` and `SKILL.md` if present
- the cognee data directory, stored under `cognee/` in the zip

Restore writes the cognee files back into the configured data directory and skips any archive entry whose path would escape it. Stop the memory worker before restoring so cognee is not writing during the restore.

Recommended before any manual repair:

```powershell
Copy-Item .agent .agent.backup -Recurse
```

## Recover cognee Or LLM Provider Outage

Expected behavior:

- Chat remains available, without long-term context while recall fails.
- `memory_session_write`, `memory_session_merge`, and `cognee_ingest` jobs retry, then dead-letter.
- If Jev is down, decisions fall back (no storage; retrieval for non-trivial messages; no tool escalation).
- `summary_generation` jobs that need the secondary LLM retry or dead-letter.

Recovery:

1. Fix provider credentials or config, then restart the API.
2. Inspect retrying and dead-letter jobs.
3. Re-queue lost work: force-merge affected sessions with `POST /api/memory/sessions/<session_id>/merge`, or re-run the backfill for legacy data.
4. Verify health returns to `OK`.

## Recover Worker Crash

Expected behavior:

- Job may remain `RUNNING`.
- Stale recovery can return it to retry handling.

Recovery:

```powershell
python -c "from src.memory.worker import recover_stale_running_jobs; print(recover_stale_running_jobs(worker_id='recovery-operator'))"
```

## Triage Dead Letters

1. Check `/api/memory/observability/dead-letter`.
2. Identify job type and redacted error.
3. A `cognee_*` job failing with "cognee is not importable" or "disabled" was dead-lettered immediately: install or enable cognee. Fix the cause before re-queuing.
4. Fix credentials, payload bug, or handler issue.
5. Keep raw DB edits as a last resort and back up first.

## Reset Long-Term Memory

To wipe the knowledge graph completely, back up first, then call `CogneeMemory.forget_all()` from a maintenance session:

```powershell
python -c "from src.memory.cognee_memory import get_cognee_memory; get_cognee_memory().forget_all()"
```

This deletes all cognee data for the deployment and cannot be undone without a backup.
