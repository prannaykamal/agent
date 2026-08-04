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

## Secondary Outage

Expected behavior:

- Chat still works.
- Worker jobs requiring secondary LLM retry or dead-letter.

Recovery:

1. Restore secondary provider credentials.
2. Confirm `/api/models` and memory config.
3. Run explicit worker step.
4. Inspect health and dead letters.

## Invalid LLM JSON

Handlers parse direct JSON and fenced JSON. Invalid output should retry without partial permanent writes.

Recovery:

1. Inspect job type and error preview.
2. Fix model/provider/prompt boundary if needed.
3. Re-run worker after retry time.

## Semantic Consolidation Failure

Candidates claimed as `IN_CONSOLIDATION` should return to `PENDING` on global pre-LLM failure, secondary outage, or invalid JSON. Candidate-specific failures should not clear the whole batch.

Recovery:

1. Inspect `consolidation_runs`.
2. Inspect candidate statuses.
3. Re-run consolidation after fixing the cause.

## Approval Linkage Mismatch

Approval decisions without procedural linkage should preserve existing non-procedural approval behavior. No skill promotion may occur without `procedural_skill_approvals` linkage.

Recovery:

1. Inspect approval request.
2. Inspect procedural approval linkage.
3. Recreate promotion request if linkage was never durably created.

## Skill Reload Failure

Reload keeps the previous runtime snapshot when generated skill files are invalid.

Recovery:

1. Inspect skill observability.
2. Validate generated `SKILL.md` frontmatter and content hash.
3. Roll back to a valid version or disable the skill.
4. Reload again.

## Corrupt Generated Skill File

Generated skill files are immutable. Do not patch old versions in place unless restoring from backup.

Recovery:

1. Disable or archive the bad version.
2. Roll back active pointer to a valid version.
3. Restore file from backup if needed.

## Retrieval Source Failure

Retrieval source failures are isolated inside `retrieve_all_sources()`. Global planner, retriever, or assembler exceptions fall back to legacy retrieval wrappers.

Recovery:

1. Run retrieval trace.
2. Check source errors.
3. Fix the source-specific reader or data issue.

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
