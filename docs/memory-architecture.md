# Memory Architecture

This document describes the completed memory architecture after Phase 10. The architecture separates user-facing chat from background memory work, keeps writes behind explicit repositories, and exposes read-only observability for operators.

## Goals

- Keep chat responsive and safe.
- Use the primary LLM only for user-facing responses.
- Use the secondary LLM only inside explicit background memory workers.
- Persist memory work durably in `memory_jobs`.
- Preserve legacy tables while adding structured stores.
- Make semantic, episodic, procedural, and summary memory independently testable.
- Keep retrieval deterministic, token-bounded, and read-only.
- Provide privacy-safe observability without exposing raw prompts, secrets, or hidden reasoning.

## LLM Role Split

Primary role:

- Resolved by `src/harness/llm_router.py`.
- Used by `src/harness/graph.py` for user-facing agent responses.
- Also used for deterministic chat title fallback boundaries.
- Must not be used for background memory processing decisions.

Secondary role:

- Resolved from job payloads by `resolve_secondary_from_job_payload()`.
- Used only by worker handlers in `src/memory/job_handlers.py`.
- May summarize, extract structured episode content, extract pending semantic candidates, consolidate semantic candidates, and classify procedural candidates.
- Must never run in the chat path.

## Chat Path

`/api/chat` in `src/api/server.py` builds an `AgentState` and invokes `agent_app` from `src/harness/graph.py`.

The graph path:

1. Manages short-term context without calling the secondary LLM.
2. Runs retrieval gate and adaptive retrieval when needed.
3. Calls the primary LLM for the assistant response.
4. Persists raw turns and loop events.
5. Enqueues durable memory jobs after successful eligible turns.

The chat response shape remains:

- `session_id`
- `session_title`
- `response`
- `retrieval_triggered`
- `retrieved_memories`
- `pending_approval_id`
- `approval_status`
- `iterations`
- `tools_used`
- `loop_events`
- `loop_trace`

No public debug metadata is added to `/api/chat`.

## Durable Memory Jobs

All asynchronous memory work is represented in `memory_jobs`.

Important modules:

- `src/memory/jobs.py`: job specs, payload builders, idempotency keys, enqueue helpers.
- `src/memory/job_repository.py`: queue persistence, claiming, retry, dead-letter, heartbeat persistence.
- `src/memory/job_router.py`: dispatches jobs to handlers.
- `src/memory/job_handlers.py`: worker-only job handlers.
- `src/memory/worker.py`: explicit worker step and loop functions.

The worker is never auto-started by chat, API startup, or retrieval. Operators must invoke worker execution explicitly.

## Worker Boundaries

Job handlers are responsible for validating payloads, resolving secondary routes only when needed, and writing through the correct store. Handlers must be idempotent where jobs can be retried.

Current real handlers:

- `summary_generation`
- `episode_generation`
- `semantic_candidate_extraction`
- `semantic_consolidation`
- `procedural_candidate_generation`
- `skill_promotion`

Current safe no-op handler:

- `procedural_consolidation`

## Short-Term Summaries

Short-term memory uses immutable summary blocks.

Important modules:

- `src/memory/token_budget.py`
- `src/memory/summary_blocks.py`
- `src/memory/short_term.py`

Raw turns are preserved. Summary generation happens through background `summary_generation` jobs. Chat remains responsive when summary generation is delayed or fails.

## Structured Episodes

Structured episodic memory is stored in `structured_episodes`.

Important modules:

- `src/memory/episode_detector.py`
- `src/memory/episode_continuation.py`
- `src/memory/episode_store.py`

The detector and continuation logic are deterministic. The LLM does not decide whether an episode exists or which action to take. The worker may call the secondary LLM only to fill structured content, and the handler ignores LLM-supplied action and trigger metadata.

Legacy `episodes` and FTS search remain available for compatibility.

## Semantic Memory

Semantic memory separates immediate explicit facts from implicit LLM candidates.

Important modules:

- `src/memory/semantic.py`
- `src/memory/semantic_store.py`
- `src/memory/semantic_candidates.py`
- `src/memory/semantic_dedup.py`
- `src/memory/embeddings.py`
- `src/memory/semantic_consolidation.py`

Permanent facts are stored in legacy `facts` for compatibility, but every permanent write must pass through `SemanticFactStore.add_explicit_fact()` and mandatory deduplication. LLM-extracted facts are written only to `pending_fact_candidates` until semantic consolidation promotes them through the dedup-aware store.

`MEMORY.md` mirrors permanent facts only.

## Procedural Memory

Procedural memory is stored as immutable generated `SKILL.md` versions plus database metadata.

Important modules:

- `src/memory/skill_files.py`
- `src/memory/skill_store.py`
- `src/memory/procedural_candidates.py`
- `src/memory/procedural_dedup.py`
- `src/memory/skill_promotion.py`
- `src/memory/skill_reloader.py`
- `src/memory/procedural.py`

Generated skills live under:

```text
.agent/skills/generated/<skill_id>/vNNNN/SKILL.md
```

User-authored skills live under `.agent/skills/user` and must never be overwritten. Candidate generation does not create skill files or versions. Skill files and `skill_versions` rows are created only after HITL approval.

## Adaptive Retrieval

Retrieval is read-only.

Important modules:

- `src/memory/retrieval_gate.py`
- `src/memory/retrieval_types.py`
- `src/memory/retrieval_ranker.py`
- `src/memory/retrieval_sources.py`
- `src/memory/retrieval_planner.py`
- `src/memory/context_assembler.py`

Retrieval skips simple greetings and simple math. When retrieval runs, it builds one memory context block with the header:

```text
[Retrieved Long-Term Memory]
```

Retrieval must not generate embeddings, write dedup events, update usage stats, enqueue jobs, or call LLMs.

## Observability Boundaries

Observability is additive and read-only.

API endpoints live under:

- `GET /api/memory/observability/health`
- `GET /api/memory/observability/jobs`
- `GET /api/memory/observability/workers`
- `GET /api/memory/observability/dead-letter`
- `POST /api/memory/observability/retrieval/trace`
- `GET /api/memory/observability/semantic`
- `GET /api/memory/observability/procedural`
- `GET /api/memory/observability/skills`
- `GET /api/memory/observability/overview`

Observability redacts secrets, credentials, raw prompt/message fields, scratchpads, hidden reasoning, and chain-of-thought content.

## Table Ownership

| Table | Owner |
|---|---|
| `raw_turns` | Short-term chat history |
| `summary_blocks` | Immutable summaries |
| `memory_jobs` | Durable queue |
| `dead_letter_jobs` | Exhausted worker failures |
| `worker_heartbeats` | Explicit worker status |
| `structured_episodes` | Structured episodic memory |
| `episodes` | Legacy episodic compatibility |
| `facts` | Permanent semantic facts |
| `pending_fact_candidates` | Pending semantic candidates |
| `semantic_embeddings` | Permanent fact embeddings |
| `semantic_dedup_events` | Dedup audit events |
| `consolidation_runs` | Semantic consolidation runs |
| `skills` | Legacy procedural compatibility |
| `skill_candidates` | Procedural candidates |
| `skill_versions` | Versioned generated skills |
| `skill_usage_stats` | Skill load/use counters |
| `procedural_skill_approvals` | HITL promotion linkage |
| `approval_requests` | Generic HITL approvals |

## Legacy Compatibility

Legacy tables remain readable. Runtime wrappers preserve existing public APIs for semantic facts, episodic search, procedural skills, and memory inspection. Legacy backfill is optional, documentation-only in Phase 11, and must never run automatically.
