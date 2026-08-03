"""Additive Phase X memory architecture schema helpers.

This module only creates schema objects. It intentionally contains no queue,
worker, memory-processing, deduplication, skill-writing, or retrieval logic.
"""

from sqlite3 import Connection


PHASE_X_MEMORY_TABLES = [
    "memory_jobs",
    "dead_letter_jobs",
    "worker_heartbeats",
    "summary_blocks",
    "structured_episodes",
    "pending_fact_candidates",
    "semantic_embeddings",
    "semantic_dedup_events",
    "consolidation_runs",
    "skill_candidates",
    "skill_versions",
    "skill_usage_stats",
    "procedural_skill_approvals",
]


def create_phase_x_memory_schema(conn: Connection) -> None:
    """Create Phase X memory schema foundations idempotently."""
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS memory_jobs (
            id TEXT PRIMARY KEY,
            job_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'QUEUED'
                CHECK (status IN ('QUEUED','RUNNING','RETRYING','SUCCEEDED','FAILED','DEAD_LETTERED','CANCELLED')),
            priority INTEGER NOT NULL DEFAULT 100 CHECK (priority >= 0),
            session_id TEXT,
            idempotency_key TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            result_json TEXT,
            error_message TEXT,
            attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
            max_attempts INTEGER NOT NULL DEFAULT 3 CHECK (max_attempts > 0),
            available_at TEXT NOT NULL DEFAULT (datetime('now')),
            locked_by TEXT,
            locked_at TEXT,
            started_at TEXT,
            completed_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_jobs_idempotency_key ON memory_jobs(idempotency_key);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_memory_jobs_status_available_priority ON memory_jobs(status, available_at, priority, created_at);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_memory_jobs_session ON memory_jobs(session_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_memory_jobs_type_status ON memory_jobs(job_type, status);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_memory_jobs_locked_by ON memory_jobs(locked_by);")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS dead_letter_jobs (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            job_type TEXT NOT NULL,
            session_id TEXT,
            idempotency_key TEXT,
            payload_json TEXT NOT NULL DEFAULT '{}',
            last_error TEXT NOT NULL,
            error_details_json TEXT,
            attempt_count INTEGER NOT NULL CHECK (attempt_count > 0),
            failed_at TEXT NOT NULL DEFAULT (datetime('now')),
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_dead_letter_jobs_job_id ON dead_letter_jobs(job_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_dead_letter_jobs_type_failed ON dead_letter_jobs(job_type, failed_at);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_dead_letter_jobs_session ON dead_letter_jobs(session_id);")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS worker_heartbeats (
            worker_id TEXT PRIMARY KEY,
            worker_type TEXT NOT NULL,
            status TEXT NOT NULL
                CHECK (status IN ('STARTING','RUNNING','IDLE','STOPPING','STOPPED','ERROR','STALE')),
            current_job_id TEXT,
            last_heartbeat_at TEXT NOT NULL DEFAULT (datetime('now')),
            started_at TEXT NOT NULL DEFAULT (datetime('now')),
            metadata_json TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_worker_heartbeats_type_status ON worker_heartbeats(worker_type, status);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_worker_heartbeats_last_seen ON worker_heartbeats(last_heartbeat_at);")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS summary_blocks (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            sequence_number INTEGER NOT NULL CHECK (sequence_number > 0),
            summary TEXT NOT NULL,
            covered_message_ids_json TEXT NOT NULL,
            start_message_id TEXT,
            end_message_id TEXT,
            source_job_id TEXT,
            token_count INTEGER NOT NULL CHECK (token_count >= 0),
            original_token_count INTEGER CHECK (original_token_count IS NULL OR original_token_count >= 0),
            model_provider TEXT,
            model_name TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_summary_blocks_session_sequence_unique ON summary_blocks(session_id, sequence_number);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_summary_blocks_session_created ON summary_blocks(session_id, created_at);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_summary_blocks_source_job ON summary_blocks(source_job_id);")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS structured_episodes (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            title TEXT NOT NULL CHECK (title <> ''),
            summary TEXT NOT NULL CHECK (summary <> ''),
            participants_json TEXT NOT NULL,
            goals_json TEXT NOT NULL,
            decisions_json TEXT NOT NULL,
            artifacts_json TEXT NOT NULL,
            topics_json TEXT NOT NULL,
            importance REAL NOT NULL CHECK (importance >= 0 AND importance <= 1),
            start_message_id TEXT NOT NULL,
            end_message_id TEXT NOT NULL,
            source TEXT NOT NULL,
            action TEXT NOT NULL CHECK (action IN ('CREATE','UPDATE','MERGE','SPLIT')),
            parent_episode_id TEXT,
            source_job_id TEXT,
            search_text TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT
        );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_structured_episodes_session_created ON structured_episodes(session_id, created_at);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_structured_episodes_importance ON structured_episodes(importance);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_structured_episodes_source ON structured_episodes(source);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_structured_episodes_action ON structured_episodes(action);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_structured_episodes_parent ON structured_episodes(parent_episode_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_structured_episodes_source_job ON structured_episodes(source_job_id);")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pending_fact_candidates (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            source_message_id TEXT,
            source_episode_id TEXT,
            fact TEXT NOT NULL CHECK (fact <> ''),
            category TEXT NOT NULL,
            confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
            explicit INTEGER NOT NULL DEFAULT 0 CHECK (explicit IN (0, 1)),
            source TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING'
                CHECK (status IN ('PENDING','IN_CONSOLIDATION','PROMOTED','DISCARDED','DEFERRED','FAILED')),
            batch_id TEXT,
            metadata_json TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            processed_at TEXT
        );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pending_fact_candidates_status_created ON pending_fact_candidates(status, created_at);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pending_fact_candidates_session ON pending_fact_candidates(session_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pending_fact_candidates_episode ON pending_fact_candidates(source_episode_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pending_fact_candidates_batch ON pending_fact_candidates(batch_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pending_fact_candidates_category ON pending_fact_candidates(category);")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS semantic_embeddings (
            id TEXT PRIMARY KEY,
            owner_type TEXT NOT NULL
                CHECK (owner_type IN ('semantic_fact','fact_candidate','structured_episode','skill_candidate','skill_version')),
            owner_id TEXT NOT NULL,
            embedding_model TEXT NOT NULL,
            embedding_dim INTEGER NOT NULL CHECK (embedding_dim > 0),
            embedding_json TEXT NOT NULL,
            content_hash TEXT NOT NULL CHECK (content_hash <> ''),
            metadata_json TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_semantic_embeddings_owner_model_unique ON semantic_embeddings(owner_type, owner_id, embedding_model);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_semantic_embeddings_owner ON semantic_embeddings(owner_type, owner_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_semantic_embeddings_hash ON semantic_embeddings(content_hash);")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS semantic_dedup_events (
            id TEXT PRIMARY KEY,
            candidate_id TEXT,
            new_fact_text TEXT NOT NULL,
            action TEXT NOT NULL CHECK (action IN ('NEW','DUPLICATE','UPDATE','MERGE')),
            target_fact_id TEXT,
            merged_fact_ids_json TEXT,
            similar_fact_ids_json TEXT,
            llm_provider TEXT,
            llm_model TEXT,
            reason TEXT,
            confidence REAL CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
            context_json TEXT,
            source_job_id TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_semantic_dedup_events_candidate ON semantic_dedup_events(candidate_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_semantic_dedup_events_target ON semantic_dedup_events(target_fact_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_semantic_dedup_events_action_created ON semantic_dedup_events(action, created_at);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_semantic_dedup_events_source_job ON semantic_dedup_events(source_job_id);")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS consolidation_runs (
            id TEXT PRIMARY KEY,
            consolidation_type TEXT NOT NULL CHECK (consolidation_type IN ('semantic','procedural')),
            trigger_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING'
                CHECK (status IN ('PENDING','RUNNING','SUCCEEDED','FAILED','PARTIAL','CANCELLED')),
            input_refs_json TEXT NOT NULL,
            output_refs_json TEXT,
            metrics_json TEXT,
            error_message TEXT,
            source_job_id TEXT,
            started_at TEXT,
            completed_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_consolidation_runs_type_status ON consolidation_runs(consolidation_type, status);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_consolidation_runs_trigger_created ON consolidation_runs(trigger_type, created_at);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_consolidation_runs_source_job ON consolidation_runs(source_job_id);")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS skill_candidates (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL CHECK (title <> ''),
            description TEXT NOT NULL,
            trigger_description TEXT NOT NULL CHECK (trigger_description <> ''),
            workflow_json TEXT NOT NULL,
            preferred_tools_json TEXT NOT NULL,
            tags_json TEXT,
            workflow_category TEXT,
            confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
            occurrences INTEGER NOT NULL DEFAULT 0 CHECK (occurrences >= 0),
            source_episode_ids_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'NEW'
                CHECK (status IN ('NEW','OBSERVING','READY_FOR_PROMOTION','WAITING_FOR_APPROVAL','PROMOTED','REJECTED')),
            dedup_group_id TEXT,
            source_job_id TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_skill_candidates_status_confidence ON skill_candidates(status, confidence);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_skill_candidates_occurrences ON skill_candidates(occurrences);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_skill_candidates_category ON skill_candidates(workflow_category);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_skill_candidates_dedup_group ON skill_candidates(dedup_group_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_skill_candidates_source_job ON skill_candidates(source_job_id);")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS skill_versions (
            id TEXT PRIMARY KEY,
            skill_id TEXT NOT NULL,
            candidate_id TEXT,
            version INTEGER NOT NULL CHECK (version > 0),
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            file_path TEXT NOT NULL CHECK (file_path <> ''),
            content_hash TEXT NOT NULL CHECK (content_hash <> ''),
            frontmatter_json TEXT NOT NULL,
            workflow_json TEXT,
            preferred_tools_json TEXT,
            tags_json TEXT,
            enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
            active INTEGER NOT NULL DEFAULT 0 CHECK (active IN (0, 1)),
            author TEXT NOT NULL,
            approval_required INTEGER NOT NULL DEFAULT 0 CHECK (approval_required IN (0, 1)),
            approval_id TEXT,
            confidence REAL CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            approved_at TEXT,
            archived_at TEXT
        );
    """)
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_skill_versions_skill_version_unique ON skill_versions(skill_id, version);")
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_skill_versions_one_active_per_skill ON skill_versions(skill_id) WHERE active = 1;")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_skill_versions_candidate ON skill_versions(candidate_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_skill_versions_enabled_active ON skill_versions(enabled, active);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_skill_versions_approval ON skill_versions(approval_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_skill_versions_name ON skill_versions(name);")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS skill_usage_stats (
            skill_id TEXT PRIMARY KEY,
            active_version_id TEXT,
            times_loaded INTEGER NOT NULL DEFAULT 0 CHECK (times_loaded >= 0),
            times_used INTEGER NOT NULL DEFAULT 0 CHECK (times_used >= 0),
            last_loaded TEXT,
            last_used TEXT,
            last_updated TEXT NOT NULL DEFAULT (datetime('now')),
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_skill_usage_stats_loaded ON skill_usage_stats(times_loaded);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_skill_usage_stats_used ON skill_usage_stats(times_used);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_skill_usage_stats_last_used ON skill_usage_stats(last_used);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_skill_usage_stats_active_version ON skill_usage_stats(active_version_id);")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS procedural_skill_approvals (
            id TEXT PRIMARY KEY,
            approval_request_id TEXT NOT NULL,
            candidate_id TEXT,
            skill_version_id TEXT,
            action TEXT NOT NULL CHECK (action IN ('PROMOTE_SKILL','MODIFY_SKILL','REJECT_SKILL')),
            status TEXT NOT NULL DEFAULT 'PENDING'
                CHECK (status IN ('PENDING','APPROVED','REJECTED','MODIFIED','CANCELLED')),
            modified_payload_json TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            decided_at TEXT,
            CHECK (candidate_id IS NOT NULL OR skill_version_id IS NOT NULL)
        );
    """)
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_procedural_skill_approvals_request_unique ON procedural_skill_approvals(approval_request_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_procedural_skill_approvals_candidate ON procedural_skill_approvals(candidate_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_procedural_skill_approvals_version ON procedural_skill_approvals(skill_version_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_procedural_skill_approvals_status ON procedural_skill_approvals(status);")

    conn.commit()
