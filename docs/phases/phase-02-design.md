# Phase 2 Design: Additive Database Schema Foundations

## 1. Executive Summary

Phase 2 adds the target database schema foundations for the approved Dual-LLM Memory Architecture without changing runtime behavior.

This phase is schema-only. It must not execute memory jobs, start new workers, perform semantic deduplication, write procedural skills, alter retrieval behavior, or migrate current runtime code to the new tables. Existing legacy tables remain authoritative for current behavior until later phases deliberately switch subsystem implementations.

Phase 2 adds additive tables for durable memory jobs, dead-letter jobs, worker heartbeats, immutable summary blocks, structured episodic memories, semantic fact candidates, semantic embeddings, dedup audit events, consolidation runs, procedural skill candidates, skill versions, skill usage stats, and procedural skill approval linkage.

The migration must work on empty databases and existing `.agent/state.db` files, be idempotent, and preserve current legacy tables: `episodes`, `facts`, `skills`, `raw_turns`, and `pending_facts`.

## 2. Inputs and Scope

This design uses `docs/implementation-roadmap.md`, `docs/phases/phase-01-design.md`, the Phase 1 contracts in `src/memory/types.py`, `src/memory/config.py`, and `src/memory/interfaces.py`, plus the current database and API implementation in `src/db.py`, `src/db_migrations.py`, and `src/api/server.py`.

In scope:

- Schema design.
- Migration design.
- API data inspector impact.
- Test plan.

Out of scope:

- Queue execution.
- Worker processing.
- Semantic deduplication behavior.
- Skill writing or skill file versioning behavior.
- Retrieval behavior.
- Backfill from legacy tables.
- Runtime switches to use the new tables.

## 3. Current DB Assessment

`src/db.py` currently owns `get_connection`, `_create_tables`, `init_db`, and legacy helpers for facts and episodes. `get_connection()` creates base tables and then calls `run_db_migrations()`. `src/db_migrations.py` owns versioned migrations through version 7.

Current memory tables to preserve unchanged:

| Table | Type | Current role | Phase 2 treatment |
|---|---|---|---|
| `episodes` | FTS5 virtual table | Legacy episodic/event search | Preserve unchanged. |
| `facts` | FTS5 virtual table | Legacy semantic facts | Preserve unchanged. |
| `skills` | Standard table | Legacy procedural skill catalog | Preserve unchanged. |
| `raw_turns` | Standard table | Uncompacted conversation turns | Preserve unchanged. |
| `pending_facts` | Standard table | Legacy low-confidence fact queue | Preserve unchanged. |

`src/api/server.py` currently duplicates hardcoded `allowed_tables` lists in `GET /api/data/tables` and `GET /api/data/table/{table_name}`. Phase 2 should add the new table names to both lists, or preferably extract one shared constant as a small local refactor.

Existing tests already cover empty DB initialization, migration versioning, data inspector behavior, and legacy table readability. Phase 2 tests should extend those expectations without changing current runtime behavior.

## 4. Proposed Schema Overview

| Table | Purpose | Future phase |
|---|---|---|
| `memory_jobs` | Durable background memory job queue | Phase 3A, 3B |
| `dead_letter_jobs` | Terminal failed job archive | Phase 3B |
| `worker_heartbeats` | Background worker liveness/status | Phase 3B, 10 |
| `summary_blocks` | Immutable short-term summary blocks | Phase 5B |
| `structured_episodes` | Normalized episodic memories | Phase 6A, 6B |
| `pending_fact_candidates` | New semantic candidate queue | Phase 7A |
| `semantic_embeddings` | Embedding records for semantic facts/final text | Phase 7B, 9A |
| `semantic_dedup_events` | Auditable dedup decisions | Phase 7B |
| `consolidation_runs` | Semantic/procedural consolidation run records | Phase 7C, 8B |
| `skill_candidates` | Procedural workflow candidates | Phase 8B |
| `skill_versions` | Versioned procedural skill file metadata | Phase 8A, 8C |
| `skill_usage_stats` | Skill retrieval/load/use metrics | Phase 8C, 9A |
| `procedural_skill_approvals` | Links skill candidates/versions to HITL approvals | Phase 8C |

Naming choices:

- Use `structured_episodes`, not `episodes_v2`, because the table contains target structured episodic memory while legacy `episodes` remains a compatibility FTS table.
- Use `pending_fact_candidates`, not `pending_facts_v2`, because legacy `pending_facts` remains untouched and the new table maps directly to Phase 1 `FactCandidate`.
- Use `procedural_skill_approvals` for approval linkage so generic `approval_requests` remains unchanged.

All JSON fields are stored as `TEXT` containing JSON. Do not require SQLite JSON1 in Phase 2.

## 5. Table-by-Table Design

### 5.1 `memory_jobs`

Purpose: durable queue table for asynchronous memory work. Phase 2 creates the table only; Phase 3A/3B add enqueue and processing.

Columns:

| Column | Type | Required | Description |
|---|---|---:|---|
| `id` | `TEXT` | yes | Stable job ID. |
| `job_type` | `TEXT` | yes | One of Phase 1 `MemoryJobType`. |
| `status` | `TEXT` | yes | Queue state, default `QUEUED`. |
| `priority` | `INTEGER` | yes | Lower number means higher priority, default `100`. |
| `session_id` | `TEXT` | no | Conversation/session association. |
| `idempotency_key` | `TEXT` | yes | Prevents duplicate job creation. |
| `payload_json` | `TEXT` | yes | Job input payload. JSON. |
| `result_json` | `TEXT` | no | Optional structured result. JSON. |
| `error_message` | `TEXT` | no | Last error summary. |
| `attempt_count` | `INTEGER` | yes | Current attempt count, default `0`. |
| `max_attempts` | `INTEGER` | yes | Retry limit copied from config. |
| `available_at` | `TEXT` | yes | Timestamp when job can be claimed. |
| `locked_by` | `TEXT` | no | Worker ID currently processing. |
| `locked_at` | `TEXT` | no | Lock acquisition timestamp. |
| `started_at` | `TEXT` | no | Processing start timestamp. |
| `completed_at` | `TEXT` | no | Completion timestamp. |
| `created_at` | `TEXT` | yes | Default `datetime('now')`. |
| `updated_at` | `TEXT` | yes | Default `datetime('now')`. |

Primary key: `id`.

Indexes: unique `idempotency_key`; `(status, available_at, priority, created_at)` for claiming; `session_id`; `(job_type, status)`; `locked_by`.

Constraints: `status IN ('QUEUED','RUNNING','RETRYING','SUCCEEDED','FAILED','CANCELLED')`; `attempt_count >= 0`; `max_attempts > 0`; `priority >= 0`.

JSON fields: `payload_json`, `result_json`.

Timestamps: `available_at`, `locked_at`, `started_at`, `completed_at`, `created_at`, `updated_at`.

Future phase: Phase 3A, Phase 3B.

### 5.2 `dead_letter_jobs`

Purpose: archive jobs that exhausted retries or failed permanently, preserving diagnostic context outside the active queue.

Columns:

| Column | Type | Required | Description |
|---|---|---:|---|
| `id` | `TEXT` | yes | Dead-letter record ID. |
| `job_id` | `TEXT` | yes | Original `memory_jobs.id`. |
| `job_type` | `TEXT` | yes | Original job type. |
| `session_id` | `TEXT` | no | Original session. |
| `idempotency_key` | `TEXT` | no | Original idempotency key. |
| `payload_json` | `TEXT` | yes | Original payload. JSON. |
| `last_error` | `TEXT` | yes | Final error summary. |
| `error_details_json` | `TEXT` | no | Structured error data. JSON. |
| `attempt_count` | `INTEGER` | yes | Attempts made before dead-letter. |
| `failed_at` | `TEXT` | yes | Final failure timestamp. |
| `created_at` | `TEXT` | yes | Dead-letter insert timestamp. |

Primary key: `id`.

Indexes: `job_id`; `(job_type, failed_at)`; `session_id`.

Constraints: `attempt_count > 0`; `job_type` should match the `memory_jobs.job_type` allowed set.

JSON fields: `payload_json`, `error_details_json`.

Timestamps: `failed_at`, `created_at`.

Future phase: Phase 3B.

### 5.3 `worker_heartbeats`

Purpose: track background worker liveness and current activity. Phase 10 can use this for real health reporting instead of static `worker_status`.

Columns:

| Column | Type | Required | Description |
|---|---|---:|---|
| `worker_id` | `TEXT` | yes | Stable worker identifier. |
| `worker_type` | `TEXT` | yes | `memory`, `scheduled`, or `maintenance`. |
| `status` | `TEXT` | yes | Worker state. |
| `current_job_id` | `TEXT` | no | Active memory job if any. |
| `last_heartbeat_at` | `TEXT` | yes | Most recent heartbeat timestamp. |
| `started_at` | `TEXT` | yes | Worker process start timestamp. |
| `metadata_json` | `TEXT` | no | Host/process/config metadata. JSON. |
| `created_at` | `TEXT` | yes | Insert timestamp. |
| `updated_at` | `TEXT` | yes | Last update timestamp. |

Primary key: `worker_id`.

Indexes: `(worker_type, status)`; `last_heartbeat_at`.

Constraints: `status IN ('STARTING','RUNNING','IDLE','STOPPING','STOPPED','ERROR','STALE')`.

JSON fields: `metadata_json`.

Timestamps: `last_heartbeat_at`, `started_at`, `created_at`, `updated_at`.

Future phase: Phase 3B, Phase 10.

### 5.4 `summary_blocks`

Purpose: immutable short-term memory summary blocks. This supports the requirement that older summaries are never regenerated.

Columns:

| Column | Type | Required | Description |
|---|---|---:|---|
| `id` | `TEXT` | yes | Summary block ID. |
| `session_id` | `TEXT` | yes | Conversation/session ID. |
| `sequence_number` | `INTEGER` | yes | Monotonic order within session. |
| `summary` | `TEXT` | yes | Summary text. |
| `covered_message_ids_json` | `TEXT` | yes | Covered raw/message IDs. JSON array. |
| `start_message_id` | `TEXT` | no | First covered message ID. |
| `end_message_id` | `TEXT` | no | Last covered message ID. |
| `source_job_id` | `TEXT` | no | Job that generated block. |
| `token_count` | `INTEGER` | yes | Tokens represented by summary. |
| `original_token_count` | `INTEGER` | no | Tokens removed from recent messages. |
| `model_provider` | `TEXT` | no | Secondary provider used. |
| `model_name` | `TEXT` | no | Secondary model used. |
| `created_at` | `TEXT` | yes | Insert timestamp. |

Primary key: `id`.

Indexes: unique `(session_id, sequence_number)`; `(session_id, created_at)`; `source_job_id`.

Constraints: `sequence_number > 0`; `token_count >= 0`; `original_token_count IS NULL OR original_token_count >= 0`.

JSON fields: `covered_message_ids_json`.

Timestamps: `created_at` only; no `updated_at`, preserving immutability.

Future phase: Phase 5B.

### 5.5 `structured_episodes`

Purpose: normalized episodic memories using the approved episode schema. This table does not replace legacy `episodes` in Phase 2.

Columns:

| Column | Type | Required | Description |
|---|---|---:|---|
| `id` | `TEXT` | yes | Episode ID. |
| `session_id` | `TEXT` | yes | Conversation/session ID. |
| `title` | `TEXT` | yes | Episode title. |
| `summary` | `TEXT` | yes | Episode summary. |
| `participants_json` | `TEXT` | yes | Participants. JSON array. |
| `goals_json` | `TEXT` | yes | Goals. JSON array. |
| `decisions_json` | `TEXT` | yes | Decisions. JSON array. |
| `artifacts_json` | `TEXT` | yes | Artifacts. JSON array. |
| `topics_json` | `TEXT` | yes | Topics. JSON array. |
| `importance` | `REAL` | yes | Importance score. |
| `start_message_id` | `TEXT` | yes | First covered message ID. |
| `end_message_id` | `TEXT` | yes | Last covered message ID. |
| `source` | `TEXT` | yes | Trigger/source such as `trimming`, `task_completed`, `explicit_remember`. |
| `action` | `TEXT` | yes | `CREATE`, `UPDATE`, `MERGE`, or `SPLIT`. |
| `parent_episode_id` | `TEXT` | no | Previous episode lineage. |
| `source_job_id` | `TEXT` | no | Job that generated or updated this episode. |
| `search_text` | `TEXT` | no | Denormalized searchable text for future retrieval. |
| `created_at` | `TEXT` | yes | Insert timestamp. |
| `updated_at` | `TEXT` | no | Future update/merge timestamp. |

Primary key: `id`.

Indexes: `(session_id, created_at)`; `importance`; `source`; `action`; `parent_episode_id`; `source_job_id`.

Constraints: `importance >= 0 AND importance <= 1`; `action IN ('CREATE','UPDATE','MERGE','SPLIT')`; `title <> ''`; `summary <> ''`.

JSON fields: `participants_json`, `goals_json`, `decisions_json`, `artifacts_json`, `topics_json`.

Timestamps: `created_at`, `updated_at`.

Future phase: Phase 6A, Phase 6B.

### 5.6 `pending_fact_candidates`

Purpose: target semantic fact candidate queue. This is separate from legacy `pending_facts`.

Columns:

| Column | Type | Required | Description |
|---|---|---:|---|
| `id` | `TEXT` | yes | Candidate ID. |
| `session_id` | `TEXT` | yes | Conversation/session ID. |
| `source_message_id` | `TEXT` | no | Message that produced the candidate. |
| `source_episode_id` | `TEXT` | no | Episode associated with candidate. |
| `fact` | `TEXT` | yes | Candidate fact text. |
| `category` | `TEXT` | yes | Fact category. |
| `confidence` | `REAL` | yes | Candidate confidence. |
| `explicit` | `INTEGER` | yes | 1 explicit, 0 inferred. |
| `source` | `TEXT` | yes | `deterministic`, `secondary_llm`, `consolidation`, etc. |
| `status` | `TEXT` | yes | Candidate lifecycle state. |
| `batch_id` | `TEXT` | no | Consolidation batch/run ID. |
| `metadata_json` | `TEXT` | no | Context/extractor metadata. JSON. |
| `created_at` | `TEXT` | yes | Insert timestamp. |
| `updated_at` | `TEXT` | yes | Last lifecycle update timestamp. |
| `processed_at` | `TEXT` | no | Final processing timestamp. |

Primary key: `id`.

Indexes: `(status, created_at)`; `session_id`; `source_episode_id`; `batch_id`; `category`.

Constraints: `confidence >= 0 AND confidence <= 1`; `explicit IN (0,1)`; `status IN ('PENDING','IN_CONSOLIDATION','PROMOTED','DISCARDED','DEFERRED','FAILED')`; `fact <> ''`.

JSON fields: `metadata_json`.

Timestamps: `created_at`, `updated_at`, `processed_at`.

Future phase: Phase 7A, Phase 7C.

### 5.7 `semantic_embeddings`

Purpose: embedding records for semantic facts, candidates, episodes, and future procedural objects.

Columns:

| Column | Type | Required | Description |
|---|---|---:|---|
| `id` | `TEXT` | yes | Embedding record ID. |
| `owner_type` | `TEXT` | yes | Owner kind. |
| `owner_id` | `TEXT` | yes | Owner record ID. |
| `embedding_model` | `TEXT` | yes | Embedding model name. |
| `embedding_dim` | `INTEGER` | yes | Vector dimension. |
| `embedding_json` | `TEXT` | yes | Embedding vector. JSON array. |
| `content_hash` | `TEXT` | yes | Hash of embedded text. |
| `metadata_json` | `TEXT` | no | Provider/version metadata. JSON. |
| `created_at` | `TEXT` | yes | Insert timestamp. |
| `updated_at` | `TEXT` | yes | Regeneration timestamp. |

Primary key: `id`.

Indexes: unique `(owner_type, owner_id, embedding_model)`; `(owner_type, owner_id)`; `content_hash`.

Constraints: `owner_type IN ('semantic_fact','fact_candidate','structured_episode','skill_candidate','skill_version')`; `embedding_dim > 0`; `content_hash <> ''`.

JSON fields: `embedding_json`, `metadata_json`.

Timestamps: `created_at`, `updated_at`.

Future phase: Phase 7B, Phase 9A.

### 5.8 `semantic_dedup_events`

Purpose: audit trail for semantic deduplication decisions.

Columns:

| Column | Type | Required | Description |
|---|---|---:|---|
| `id` | `TEXT` | yes | Dedup event ID. |
| `candidate_id` | `TEXT` | no | Related fact candidate. |
| `new_fact_text` | `TEXT` | yes | Proposed fact text. |
| `action` | `TEXT` | yes | `NEW`, `DUPLICATE`, `UPDATE`, or `MERGE`. |
| `target_fact_id` | `TEXT` | no | Existing/final semantic fact target. |
| `merged_fact_ids_json` | `TEXT` | no | Merged fact IDs. JSON array. |
| `similar_fact_ids_json` | `TEXT` | no | Similar fact IDs. JSON array. |
| `llm_provider` | `TEXT` | no | Secondary provider used. |
| `llm_model` | `TEXT` | no | Secondary model used. |
| `reason` | `TEXT` | no | Human-readable reason. |
| `confidence` | `REAL` | no | Decision confidence. |
| `context_json` | `TEXT` | no | Conversation/episode context. JSON. |
| `source_job_id` | `TEXT` | no | Job that made decision. |
| `created_at` | `TEXT` | yes | Insert timestamp. |

Primary key: `id`.

Indexes: `candidate_id`; `target_fact_id`; `(action, created_at)`; `source_job_id`.

Constraints: `action IN ('NEW','DUPLICATE','UPDATE','MERGE')`; `confidence IS NULL OR (confidence >= 0 AND confidence <= 1)`.

JSON fields: `merged_fact_ids_json`, `similar_fact_ids_json`, `context_json`.

Timestamps: `created_at`.

Future phase: Phase 7B.

### 5.9 `consolidation_runs`

Purpose: track semantic and procedural consolidation runs for observability, idempotency, and recovery.

Columns:

| Column | Type | Required | Description |
|---|---|---:|---|
| `id` | `TEXT` | yes | Consolidation run ID. |
| `consolidation_type` | `TEXT` | yes | `semantic` or `procedural`. |
| `trigger_type` | `TEXT` | yes | `episode_count`, `candidate_count`, `daily_idle`, `manual`, etc. |
| `status` | `TEXT` | yes | Run lifecycle state. |
| `input_refs_json` | `TEXT` | yes | Input IDs. JSON. |
| `output_refs_json` | `TEXT` | no | Output IDs. JSON. |
| `metrics_json` | `TEXT` | no | Counts, token usage, timing/cost metadata. JSON. |
| `error_message` | `TEXT` | no | Error summary. |
| `source_job_id` | `TEXT` | no | Job that ran consolidation. |
| `started_at` | `TEXT` | no | Start timestamp. |
| `completed_at` | `TEXT` | no | Completion timestamp. |
| `created_at` | `TEXT` | yes | Insert timestamp. |
| `updated_at` | `TEXT` | yes | Last update timestamp. |

Primary key: `id`.

Indexes: `(consolidation_type, status)`; `(trigger_type, created_at)`; `source_job_id`.

Constraints: `consolidation_type IN ('semantic','procedural')`; `status IN ('PENDING','RUNNING','SUCCEEDED','FAILED','PARTIAL','CANCELLED')`.

JSON fields: `input_refs_json`, `output_refs_json`, `metrics_json`.

Timestamps: `started_at`, `completed_at`, `created_at`, `updated_at`.

Future phase: Phase 7C, Phase 8B.

### 5.10 `skill_candidates`

Purpose: procedural workflow candidates generated from episodes or explicit permanent instructions before promotion and approval.

Columns:

| Column | Type | Required | Description |
|---|---|---:|---|
| `id` | `TEXT` | yes | Candidate ID. |
| `title` | `TEXT` | yes | Candidate title. |
| `description` | `TEXT` | yes | Candidate description. |
| `trigger_description` | `TEXT` | yes | When this workflow applies. |
| `workflow_json` | `TEXT` | yes | Structured workflow steps. JSON array. |
| `preferred_tools_json` | `TEXT` | yes | Preferred tools. JSON array. |
| `tags_json` | `TEXT` | no | Tags/categories. JSON array. |
| `workflow_category` | `TEXT` | no | Deterministic category. |
| `confidence` | `REAL` | yes | Candidate confidence. |
| `occurrences` | `INTEGER` | yes | Supporting occurrence count. |
| `source_episode_ids_json` | `TEXT` | yes | Supporting episode IDs. JSON array. |
| `status` | `TEXT` | yes | Phase 1 `SkillCandidateStatus`. |
| `dedup_group_id` | `TEXT` | no | Candidate dedup group ID. |
| `source_job_id` | `TEXT` | no | Job that generated/updated candidate. |
| `created_at` | `TEXT` | yes | Insert timestamp. |
| `updated_at` | `TEXT` | yes | Last update timestamp. |

Primary key: `id`.

Indexes: `(status, confidence)`; `occurrences`; `workflow_category`; `dedup_group_id`; `source_job_id`.

Constraints: `status IN ('NEW','OBSERVING','READY_FOR_PROMOTION','WAITING_FOR_APPROVAL','PROMOTED','REJECTED')`; `confidence >= 0 AND confidence <= 1`; `occurrences >= 0`; `title <> ''`; `trigger_description <> ''`.

JSON fields: `workflow_json`, `preferred_tools_json`, `tags_json`, `source_episode_ids_json`.

Timestamps: `created_at`, `updated_at`.

Future phase: Phase 8B, Phase 8C.

### 5.11 `skill_versions`

Purpose: metadata for versioned procedural skill files. Supports the requirement that generated skill updates never overwrite existing versions.

Columns:

| Column | Type | Required | Description |
|---|---|---:|---|
| `id` | `TEXT` | yes | Skill version ID. |
| `skill_id` | `TEXT` | yes | Stable logical skill ID. |
| `candidate_id` | `TEXT` | no | Source candidate if generated. |
| `version` | `INTEGER` | yes | Version number within skill. |
| `name` | `TEXT` | yes | Skill name. |
| `description` | `TEXT` | yes | Skill description. |
| `file_path` | `TEXT` | yes | Path to `SKILL.md`. |
| `content_hash` | `TEXT` | yes | Hash of file contents. |
| `frontmatter_json` | `TEXT` | yes | Parsed YAML frontmatter as JSON. |
| `workflow_json` | `TEXT` | no | Parsed workflow steps. JSON. |
| `preferred_tools_json` | `TEXT` | no | Preferred tools. JSON array. |
| `tags_json` | `TEXT` | no | Tags. JSON array. |
| `enabled` | `INTEGER` | yes | 1 enabled, 0 disabled. |
| `active` | `INTEGER` | yes | 1 if active version for skill. |
| `author` | `TEXT` | yes | `user`, `assistant`, or source. |
| `approval_required` | `INTEGER` | yes | Whether approval was required. |
| `approval_id` | `TEXT` | no | Linked approval request. |
| `confidence` | `REAL` | no | Candidate confidence at approval. |
| `created_at` | `TEXT` | yes | Insert timestamp. |
| `updated_at` | `TEXT` | yes | Metadata update timestamp. |
| `approved_at` | `TEXT` | no | Approval timestamp. |
| `archived_at` | `TEXT` | no | Archive timestamp. |

Primary key: `id`.

Indexes: unique `(skill_id, version)`; partial unique active version per `skill_id` where `active = 1`; `candidate_id`; `(enabled, active)`; `approval_id`; `name`.

Constraints: `version > 0`; `enabled IN (0,1)`; `active IN (0,1)`; `approval_required IN (0,1)`; `confidence IS NULL OR (confidence >= 0 AND confidence <= 1)`; `file_path <> ''`; `content_hash <> ''`.

JSON fields: `frontmatter_json`, `workflow_json`, `preferred_tools_json`, `tags_json`.

Timestamps: `created_at`, `updated_at`, `approved_at`, `archived_at`.

Future phase: Phase 8A, Phase 8C.

### 5.12 `skill_usage_stats`

Purpose: procedural skill load/use statistics for retrieval ranking.

Columns:

| Column | Type | Required | Description |
|---|---|---:|---|
| `skill_id` | `TEXT` | yes | Logical skill ID. |
| `active_version_id` | `TEXT` | no | Current active version. |
| `times_loaded` | `INTEGER` | yes | Number of retrieval loads. |
| `times_used` | `INTEGER` | yes | Number of confirmed uses. |
| `last_loaded` | `TEXT` | no | Last load timestamp. |
| `last_used` | `TEXT` | no | Last use timestamp. |
| `last_updated` | `TEXT` | yes | Last stats update. |
| `created_at` | `TEXT` | yes | Insert timestamp. |

Primary key: `skill_id`.

Indexes: `times_loaded`; `times_used`; `last_used`; `active_version_id`.

Constraints: `times_loaded >= 0`; `times_used >= 0`.

JSON fields: none.

Timestamps: `last_loaded`, `last_used`, `last_updated`, `created_at`.

Future phase: Phase 8C, Phase 9A.

### 5.13 `procedural_skill_approvals`

Purpose: link procedural skill candidates and skill versions to HITL approval requests without altering generic `approval_requests`.

Columns:

| Column | Type | Required | Description |
|---|---|---:|---|
| `id` | `TEXT` | yes | Link record ID. |
| `approval_request_id` | `TEXT` | yes | Existing `approval_requests.id`. |
| `candidate_id` | `TEXT` | no | Skill candidate awaiting approval. |
| `skill_version_id` | `TEXT` | no | Final skill version if created. |
| `action` | `TEXT` | yes | Approval action type. |
| `status` | `TEXT` | yes | Approval lifecycle status. |
| `modified_payload_json` | `TEXT` | no | User modifications before approval. JSON. |
| `created_at` | `TEXT` | yes | Insert timestamp. |
| `decided_at` | `TEXT` | no | Approval/rejection timestamp. |

Primary key: `id`.

Indexes: unique `approval_request_id`; `candidate_id`; `skill_version_id`; `status`.

Constraints: `action IN ('PROMOTE_SKILL','MODIFY_SKILL','REJECT_SKILL')`; `status IN ('PENDING','APPROVED','REJECTED','MODIFIED','CANCELLED')`; `candidate_id IS NOT NULL OR skill_version_id IS NOT NULL`.

JSON fields: `modified_payload_json`.

Timestamps: `created_at`, `decided_at`.

Future phase: Phase 8C.

## 6. Index and Constraint Plan

Index principles:

- Use indexes for queue claiming, session lookups, lifecycle status filtering, and data inspector usefulness.
- Avoid speculative indexes over JSON fields.
- Add indexes with `CREATE INDEX IF NOT EXISTS` or `CREATE UNIQUE INDEX IF NOT EXISTS`.
- Keep tables as normal rowid tables so current data inspector `ORDER BY rowid DESC` remains compatible.

Constraint principles:

- Use `CHECK` constraints for enum-like lifecycle values from Phase 1 types.
- Use `CHECK` constraints for confidence, importance, attempts, token counts, booleans, and version numbers.
- Avoid cascading deletes in Phase 2. Auditability and data safety are higher priority.
- Reference columns should be indexed, but Phase 2 should not depend on foreign key enforcement unless the app later enables `PRAGMA foreign_keys = ON` consistently.

Timestamp policy:

- Store timestamps as `TEXT` using SQLite `datetime('now')` defaults for creation fields.
- Later repository layers may standardize UTC ISO 8601 formatting.

JSON policy:

- Store JSON as `TEXT`.
- Use `_json` suffix for JSON object/array fields.
- Do not require SQLite JSON1 in Phase 2.

## 7. Migration Strategy

Current migrations end at version 7. Phase 2 should add version 8:

- Version 8: `Add Phase X memory architecture schema foundations`.

Recommended implementation approach:

1. Add table creation helpers in optional `src/memory/schema.py` or private helper functions in `src/db_migrations.py`.
2. Call those helpers from migration version 8.
3. Keep all DDL idempotent.
4. Update the API data inspector allow-list after table names are finalized.

Because current `get_connection()` calls `_create_tables(conn)` before `run_db_migrations(target_path)`, implementation must avoid migration recursion. The preferred versioned source of truth is migration version 8. If `_create_tables` also calls a helper for empty DB convenience, that helper must be strictly idempotent and must not insert migration records.

Empty DB flow:

1. `get_connection()` creates legacy/base tables.
2. `run_db_migrations()` creates `schema_migrations`.
3. Migrations 1 through 8 are applied.
4. New Phase 2 tables and legacy tables all exist.

Existing DB at version 7 flow:

1. `run_db_migrations()` detects current version 7.
2. Applies only version 8.
3. Creates new tables/indexes with `IF NOT EXISTS`.
4. Inserts a single version 8 migration row.
5. Existing data remains untouched.

Idempotency requirements:

- Every `CREATE TABLE` uses `IF NOT EXISTS`.
- Every `CREATE INDEX` uses `IF NOT EXISTS`.
- Migration version insert occurs once via the existing `ver > current_version` loop.
- Re-running `run_db_migrations()` does not duplicate version 8 or fail on existing objects.

No backfill in Phase 2:

- Do not backfill legacy `episodes` into `structured_episodes`.
- Do not backfill legacy `pending_facts` into `pending_fact_candidates`.
- Do not backfill legacy `skills` into `skill_versions`.
- Do not backfill legacy `facts` into `semantic_embeddings`.

## 8. Compatibility Strategy

Runtime compatibility:

- Current code continues to read/write `episodes`, `facts`, `skills`, `raw_turns`, and `pending_facts`.
- No runtime code is redirected to Phase 2 tables.
- No queue processing or worker behavior starts in this phase.

API compatibility:

- Existing endpoints remain compatible: `/api/chat`, `/api/memory`, `/api/memory/full`, `/api/skills`, `/api/data/tables`, `/api/data/table/{table_name}`, and `/api/system/health`.
- The only visible API change is that the read-only data inspector can list and inspect the new tables.

Schema compatibility:

- Existing table names and columns are not renamed, removed, or altered.
- New tables do not share names with legacy tables.
- New tables use nullable reference columns where future relationships are not guaranteed yet.

## 9. API/Data Inspector Impact

`src/api/server.py` should include these new tables in the data inspector allow-list:

- `memory_jobs`
- `dead_letter_jobs`
- `worker_heartbeats`
- `summary_blocks`
- `structured_episodes`
- `pending_fact_candidates`
- `semantic_embeddings`
- `semantic_dedup_events`
- `consolidation_runs`
- `skill_candidates`
- `skill_versions`
- `skill_usage_stats`
- `procedural_skill_approvals`

Design recommendation:

- Extract a single `ALLOWED_DATA_TABLES` constant if modifying `src/api/server.py`; this avoids drift between `/api/data/tables` and `/api/data/table/{table_name}`.
- Do not add mutation endpoints for these tables.
- Do not change `/api/system/health` to interpret `worker_heartbeats` yet; that belongs to Phase 10.

## 10. Relationship To Phase 1 Types

| Phase 1 model/type | Phase 2 table |
|---|---|
| `SummaryBlock` | `summary_blocks` |
| `EpisodicMemory` | `structured_episodes` |
| `FactCandidate` | `pending_fact_candidates` |
| `SkillCandidate` | `skill_candidates` |
| `SkillWorkflowStep` | `skill_candidates.workflow_json`, `skill_versions.workflow_json` |
| `MemoryJobType` | `memory_jobs.job_type`, `dead_letter_jobs.job_type` |
| `DedupAction` | `semantic_dedup_events.action` |
| `EpisodeAction` | `structured_episodes.action` |
| `SkillCandidateStatus` | `skill_candidates.status` |

Phase 2 should not require changes to Phase 1 type definitions unless implementation discovers a naming mismatch.

## 11. Test Plan

New tests should be added in:

- `tests/test_phase2_schema_foundations.py`
- `tests/test_phase2_data_inspector.py`

Schema initialization tests:

- Create an empty temp DB with `init_db(db_file)`.
- Verify all Phase 2 tables exist.
- Verify legacy tables still exist.
- Verify key columns using `PRAGMA table_info(table_name)`.
- Verify expected indexes using `PRAGMA index_list(table_name)`.

Migration tests:

- Create a DB at current version 7 and run `run_db_migrations()`.
- Verify schema version is at least 8.
- Run `run_db_migrations()` twice and verify only one version 8 row exists.
- Verify migration from an old partial DB still reaches version 8.
- Verify existing rows in `episodes`, `facts`, `skills`, and `raw_turns` remain readable after migration.

Constraint tests:

- Invalid `memory_jobs.status` raises `sqlite3.IntegrityError`.
- Duplicate `memory_jobs.idempotency_key` raises `sqlite3.IntegrityError`.
- Invalid `structured_episodes.action` raises `sqlite3.IntegrityError`.
- `structured_episodes.importance` outside 0-1 raises `sqlite3.IntegrityError`.
- Invalid `semantic_dedup_events.action` raises `sqlite3.IntegrityError`.
- Invalid `skill_candidates.status` raises `sqlite3.IntegrityError`.
- Duplicate `(skill_id, version)` in `skill_versions` raises `sqlite3.IntegrityError`.
- Negative `skill_usage_stats.times_used` raises `sqlite3.IntegrityError`.

API/data inspector tests:

- `GET /api/data/tables` includes all new tables.
- `GET /api/data/table/{new_table}` returns 200 and the expected response shape for every new table.
- Unknown table names still return 400.
- Existing data inspector tests continue to pass.

Regression tests to run:

- `tests/test_harness.py`
- `tests/test_reliability_and_backup.py`
- `tests/test_p6_db_and_backup_reliability.py`
- `tests/test_frontend_api.py`
- `tests/test_api_server.py`
- Full suite if feasible.

## 12. Risks and Mitigation

| Risk | Impact | Mitigation |
|---|---|---|
| Accidentally altering legacy tables | Breaks current runtime behavior | Use only additive tables/indexes; do not alter legacy memory tables. |
| Migration recursion between `_create_tables` and `run_db_migrations` | Initialization failures | Keep helpers idempotent and avoid helper-to-migration calls. |
| Strict foreign keys block partial existing data | Migration failure on real DBs | Prefer indexed reference columns; avoid cascading FK behavior in Phase 2. |
| SQLite JSON1 unavailable | JSON constraints fail | Store JSON as `TEXT`; validate later in repository/service layers. |
| Data inspector allow-list drift | Some tables inaccessible | Extract one allow-list constant or update both lists together. |
| New indexes slow migration | Slower startup | Index only lifecycle/session/claim fields needed by future phases. |
| Naming conflict with legacy `pending_facts` | Runtime confusion | Use `pending_fact_candidates` and preserve `pending_facts`. |
| Schema implies behavior exists | Product confusion | Document these as foundational tables until later phases wire behavior. |

## 13. Acceptance Criteria

Phase 2 is complete when:

- Migration version 8 is added for Phase X memory schema foundations.
- Empty DB initialization creates all legacy tables and all Phase 2 tables.
- Existing DB migration from version 7 creates all Phase 2 tables without data loss.
- Re-running migrations is idempotent.
- Legacy tables `episodes`, `facts`, `skills`, `raw_turns`, and `pending_facts` are preserved unchanged.
- No runtime behavior switches to the new tables.
- No queue execution, worker processing, semantic deduplication, skill writing, or retrieval behavior is implemented.
- `/api/data/tables` includes the new tables.
- `/api/data/table/{table_name}` can inspect each new table.
- New schema tests validate table existence, indexes, key constraints, and idempotency.
- Existing DB, memory, API, and migration tests continue to pass.

## 14. Implementation Notes For Phase 2

These notes are design guidance only:

- Prefer a single place for Phase 2 DDL, such as `src/memory/schema.py`, to keep `db_migrations.py` readable.
- Keep DDL strings deterministic and easy to inspect in tests.
- Use `TEXT` primary keys for new architecture tables to match generated IDs and cross-system references.
- Use normal rowid tables so the existing data inspector query `ORDER BY rowid DESC` continues to work.
- Do not create triggers in Phase 2. Later application code should manage `updated_at` explicitly.
- Do not add FTS5 tables for new memories in Phase 2 unless a later phase explicitly requires them. The structured schema includes `search_text` where helpful.
