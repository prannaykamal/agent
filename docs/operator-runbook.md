# Operator Runbook

This runbook covers day-to-day operation of the memory architecture.

## Start The Backend

```powershell
python src/api/server.py
```

The server initializes directories and the SQLite schema through `ensure_system_initialized()`.

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
- `.agent/MEMORY.md` when missing
- `.agent/SOUL.md` when missing
- `.agent/SKILL.md` compatibility index when missing
- `.agent/skills/generated`
- `.agent/skills/user`
- SQLite tables and migrations

Existing `.agent/SKILL.md` and user-authored skill files must not be overwritten.

## Run One Memory Worker Step

Use one-step execution for diagnosis:

```powershell
python -c "from src.memory.worker import process_one_memory_job; print(process_one_memory_job(worker_id='memory-worker-manual'))"
```

## Run The Explicit Memory Worker Loop

```powershell
python -c "from src.memory.worker import run_memory_worker_loop; run_memory_worker_loop(worker_id='memory-worker-1')"
```

The worker is explicit. It is not auto-started by chat, retrieval, or normal API startup.

## Check Memory Health

```powershell
curl http://localhost:8000/api/memory/observability/health
```

Health summarizes schema, queue, workers, dead letters, semantic pipeline, procedural pipeline, and skills.

## Inspect Jobs

```powershell
curl "http://localhost:8000/api/memory/observability/jobs?limit=50"
curl "http://localhost:8000/api/memory/observability/jobs?status=RETRYING"
curl "http://localhost:8000/api/memory/observability/jobs?job_type=semantic_consolidation"
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

Dead-letter details are redacted. Use the job type, status, attempt count, and last error preview to decide whether a code/config fix is needed.

## Run Retrieval Trace

```powershell
curl -X POST http://localhost:8000/api/memory/observability/retrieval/trace -H "Content-Type: application/json" -d "{\"query\":\"what do you remember about deployment?\",\"session_id\":\"default_session\"}"
```

Retrieval trace is read-only. It does not create chat turns, enqueue jobs, write memory, or call LLMs. Prompt block output is hidden by default.

## Review Semantic Pipeline

```powershell
curl http://localhost:8000/api/memory/observability/semantic
```

Review pending candidates, dedup events, and consolidation runs. LLM-extracted candidates must remain pending until consolidation promotes them through the dedup-aware store.

## Review Procedural Pipeline

```powershell
curl http://localhost:8000/api/memory/observability/procedural
```

Review skill candidates and approval linkage. Candidate generation does not create active skills.

## Approve Or Reject Procedural Skill Promotion

Use the existing approval endpoint:

```powershell
curl -X POST http://localhost:8000/api/approvals/<request_id>/decision -H "Content-Type: application/json" -d "{\"decision\":\"APPROVED\"}"
curl -X POST http://localhost:8000/api/approvals/<request_id>/decision -H "Content-Type: application/json" -d "{\"decision\":\"REJECTED\"}"
```

Approval creates a generated skill version only after the generic approval decision is accepted and procedural linkage is found. Rejection creates no skill file or version.

## Reload Skill Snapshot

Use `SkillRuntimeReloader.reload_active_skills()` from an explicit maintenance command or diagnostic session. Reload records `times_loaded` and keeps the previous snapshot if a generated skill file is invalid.

## Backup And Restore

Back up both:

- SQLite database file.
- `.agent/skills` directory.

Recommended before any manual repair:

```powershell
Copy-Item .agent .agent.backup -Recurse
Copy-Item agent.db agent.db.backup
```

Adjust paths for the configured environment.

## Recover Secondary Model Outage

Expected behavior:

- Chat remains available.
- Worker jobs requiring secondary LLM retry or dead-letter.

Recovery:

1. Fix provider credentials/config.
2. Inspect retrying and dead-letter jobs.
3. Run explicit worker step or loop.
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
3. Fix credentials, payload bug, or handler issue.
4. Keep raw DB edits as a last resort and back up first.

## Roll Back Or Disable Generated Skill

Use `SkillVersionStore.rollback_to_version()` or `disable_skill()` from an explicit maintenance path. Rollback moves the active pointer only. It does not rewrite old `SKILL.md` files.
