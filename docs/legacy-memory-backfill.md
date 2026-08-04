# Legacy Memory Backfill

Phase 11 does not run automatic legacy memory backfill. This document defines the safe strategy for a future, separately approved backfill.

## Principles

- Backfill is opt-in.
- Dry-run comes first.
- Backup is required before mutation.
- Legacy tables remain readable.
- Backfill must be idempotent.
- Backfill must produce an audit report.
- Backfill must not run during chat, startup, retrieval, or worker auto-start.

## Legacy Sources

Safe to inspect:

- `facts`
- `episodes`
- `skills`
- `raw_turns`
- `pending_facts`

Unsafe to rewrite in bulk:

- `facts`, unless dedup-aware permanent write APIs are used.
- `episodes`, because legacy FTS behavior is compatibility-sensitive.
- User-authored skill files.

## Target Stores

Potential targets:

- `structured_episodes`
- `summary_blocks`
- `pending_fact_candidates`
- `skill_versions`
- `skill_candidates`

Any permanent semantic target must pass through `SemanticFactStore.add_explicit_fact()`. Any generated skill target must pass through approval and `SkillVersionStore`.

## Dry-Run Report

A future dry-run should report:

- Source table and row ID.
- Proposed target table.
- Proposed action.
- Confidence.
- Idempotency key.
- Reason skipped, if skipped.
- Estimated affected rows.

## Backup Requirement

Back up both:

- SQLite DB.
- `.agent/skills`.

Do not proceed if either backup fails.

## Reversibility

Backfill should write source metadata so inserted records can be identified. Reversal should prefer restoring from backup over ad hoc deletes.

## Phase 11 Position

Phase 11 may add tests and documentation for backfill readiness. It must not automatically backfill legacy data.
