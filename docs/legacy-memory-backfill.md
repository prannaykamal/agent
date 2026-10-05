# Legacy Memory Backfill

Long-term memory now lives in a cognee knowledge graph (see [Memory Architecture](memory-architecture.md)). Knowledge stored by the earlier semantic, episodic, and procedural stores is not visible to retrieval until it is imported into cognee once.

The importer is `src/memory/cognee_backfill.py`.

## Principles

- Backfill is opt-in. It never runs during chat, startup, retrieval, or worker auto-start.
- Dry-run comes first.
- Legacy rows are read, never modified or deleted.
- Backfill is idempotent: documents are batched into `cognee_ingest` jobs keyed by content hash, so re-running does not queue duplicates.
- The backfill only enqueues `cognee_ingest` jobs. The memory worker writes them straight into the main graph with `cognee.remember` (no session cache, no Jev decision).

## Legacy Sources

These tables exist only in databases created before cognee; new databases do not create them. The importer skips any table that is missing.

| Table | Imported as | Kind |
|---|---|---|
| `facts` | `Fact about the user (<category>): <text>` | `facts` |
| `structured_episodes` | Title, summary, decisions, and topics | `episodes` |
| `episodes` | `Past conversation (<timestamp>): <content>` | `episodes` |
| `skills` | Name, purpose, triggers, and steps | `procedures` |
| `skill_versions` (active, enabled, not archived) | The generated `SKILL.md` file, or name, description, and workflow if the file is missing | `procedures` |

Not imported: `raw_turns` (short-term history), `pending_facts` and `pending_fact_candidates` (unconfirmed candidates), and `skill_candidates` (unapproved skills).

## Running It

1. Back up first: `POST /api/system/backup` or the Overview page. The backup includes `state.db` and `.agent/cognee`.
2. Dry run and review the counts:

   ```bash
   python -m src.memory.cognee_backfill --dry-run
   ```

   ```json
   {
     "dry_run": true,
     "documents_by_table": {"facts": 6, "structured_episodes": 0, "episodes": 0, "skills": 0, "skill_versions": 0},
     "documents_total": 6,
     "jobs_queued": 0,
     "jobs_already_present": 0
   }
   ```

3. Queue the import:

   ```bash
   python -m src.memory.cognee_backfill
   ```

4. Make sure the memory worker is running (it starts with the API). Watch `cognee_ingest` in Memory Ops or `GET /api/memory/observability/long-term`.
5. Verify with a search: `POST /api/memory/search` with a query you expect an imported fact to answer.

## Reversibility

Imported documents are ordinary cognee data. To undo an import, restore the pre-import backup, which restores `.agent/cognee` along with `state.db`.
