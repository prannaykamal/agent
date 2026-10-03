# Memory Architecture

The assistant has two kinds of memory, and they never substitute for each other:

| | Short-term context | Long-term memory |
|---|---|---|
| What | The current conversation | Durable knowledge about the user |
| Where | Raw turns + immutable summary blocks in SQLite | One cognee knowledge graph |
| Managed by | Existing trimming and summarization (`manage_memory`) | Jev decisions + cognee |
| Seen by the primary LLM | Always, within the context budget | Only when Jev says retrieval is needed |

Long-term memory used to be three separate stores (semantic facts, structured episodes, procedural skills) with their own extractors, dedup, consolidation, retrievers, and rankers. All of that is gone. Facts, episodes, and procedures are now just kinds of knowledge inside one cognee graph.

## Components

- **Primary agent LLM**: unchanged. Reasons, plans, selects tools, and writes every user-facing answer.
- **Jev** (`src/memory/jev.py`): a small decision/routing model behind an OpenAI-compatible endpoint. It answers yes/no questions only. It is not an agent: it never selects tools, never writes memory itself, and can never approve anything.
- **cognee** (`src/memory/cognee_memory.py`): the single long-term memory backend. No other module imports cognee.
- **Secondary LLM**: still used only by the `summary_generation` worker job for short-term summaries.

## Turn Flow

```text
User query
   │
ingest ─────────── log raw turn
   │
manage_memory ──── existing trimming + summary blocks (short-term context)
   │
memory_router ──── Jev: {should_store, should_retrieve}   (one call for both)
   │                 └─ should_retrieve → cognee recall over the MAIN graph
   │                                       → "[Retrieved Long-Term Memory]" block
agent ──────────── primary LLM
   │
hitl_check / tools ── policy + HITL (Jev may escalate medium-risk calls, never de-escalate)
   │
consolidate ────── should_store → queue memory_session_write
```

### Jev memory decision

`node_memory_router` calls `JevClient.decide_memory(query, previous_assistant_reply)` once per user message. The single call returns both decisions:

```json
{"should_store": true, "should_retrieve": false}
```

- Greetings, acknowledgements, and bare arithmetic are answered by rule (`src/memory/retrieval_gate.py`) with no model call: store = false, retrieve = false.
- Approval resumes re-run the graph without a new user message, so Jev is not called again.
- `MEMORY_STORAGE_ENABLED=false` or `MEMORY_RETRIEVAL_ENABLED=false` override Jev's answer. With both off, or `COGNEE_ENABLED=false`, Jev is not called at all.
- Output is validated with a strict schema (`StrictBool`); fenced JSON is accepted, anything else is rejected.
- **Fallback** when Jev is not configured, times out, errors, or returns invalid output: `should_store = false` (never store unvetted content) and `should_retrieve = true` (retrieval is read-only, so failing open preserves the old behaviour).

Both decisions are kept in graph state (`memory_storage_decision`, `memory_retrieval_decision`), separate from tool execution state.

## Storage: Session Graph, Then Main Graph

```text
should_store = true
   │
consolidate ── queue memory_session_write  (only for completed, non-HITL-paused turns)
   │
worker ─────── cognee.remember(turn, session_id=<user>__<session>, self_improvement=False)
   │           queue memory_session_merge due at now + SESSION_IDLE_TIMEOUT
   │
   … conversation continues …
   │
worker ─────── memory_session_merge runs when due:
                 conversation still active?  → reschedule for last activity + timeout
                 nothing new since last merge? → no-op (duplicate idle event)
                 otherwise → cognee.improve(dataset, session_ids=[<user>__<session>])
```

- The **session graph** is cognee's session cache for that conversation (SQLite-backed under the cognee data directory, so it survives restarts). It is not the agent's context window and is never searched by retrieval.
- **Idle detection** uses the latest `raw_turns` row for the session, so any message (stored or not) keeps the session active.
- **Exactly-once merging**: each successful merge records how many successful session writes it covered (`merged_write_count`). A merge with nothing new is a no-op, and merge jobs are keyed by their due time, so duplicate idle events collapse. Write counts only increase, which makes this race-free.
- **Continued sessions**: after a merge, new worth-storing messages in the same session go to the same cognee session and trigger another merge after the next idle period.
- **Failures**: write and merge failures retry with the queue's backoff, then dead-letter. A merge that cognee reports as `errored`, still `running`, or blocked by another run's lock is retried. A lock held by a run that agreed to cover these entries (`rerun_requested`) counts as success. `POST /api/memory/sessions/{session_id}/merge` forces a merge for recovery.
- cognee's own automatic session bridging is disabled (`IMPROVE_AUTO_ENABLED=false`) so merges follow `SESSION_IDLE_TIMEOUT`.

Explicit writes skip Jev and the session: `POST /api/memory/fact`, `POST /api/memory/procedure`, and the legacy backfill queue `cognee_ingest` jobs that call `cognee.remember(...)` without a session, writing straight into the main graph.

## Retrieval

When `should_retrieve` is true, `node_memory_router`:

1. Calls `CogneeMemory.recall(query)`: `cognee.search` over the user's main-graph dataset with the configured search type. The default, `SUMMARIES`, returns cognee's distilled facts (for example "Mira is the user's sister. Mira lives in Lisbon."). `CHUNKS` returns the raw stored text. `GRAPH_COMPLETION` and `RAG_COMPLETION` are called with `only_context=True`, so cognee returns context instead of its own answer, but in cognee 1.6 that context is a whole rendered prompt template, which is why it is not the default. Bounded by `MEMORY_COGNEE_RECALL_TIMEOUT_SECONDS` and `MEMORY_COGNEE_TOP_K`.
2. Drops snippets already present verbatim in the current conversation.
3. Truncates to `MEMORY_COGNEE_RETRIEVAL_TOKEN_BUDGET` (header included) and appends one clearly labelled system message:

```text
[Retrieved Long-Term Memory]
Stored knowledge about the user from past conversations (not the current conversation):
- ...
```

An empty graph, a recall error, or a timeout means no block is injected and the turn continues normally. The whole graph is never sent to the model.

## Jev In Tool Calling

Tool selection stays with the primary LLM, and the existing policy and HITL stay authoritative. Jev is consulted at exactly one point: in `node_tools`, before executing a call that policy would run **directly** and that is either medium-risk (`create_task`, `update_task`, `checkpoint`, `lock_resource`, `publish_event`) or marked confirmation-recommended (for example a sensitive web search).

```json
{"requires_approval": true, "reason": "user did not ask for a task"}
```

- `requires_approval = true` routes the call into the existing HITL pause (`_pause_for_high_risk_tool`); it runs only after a human approves.
- High-risk and approval-required calls go to HITL by policy alone; Jev is not consulted.
- Low-risk reads are not reviewed.
- Jev failure, timeout, or malformed output means no escalation, so the existing policy outcome stands.
- `TOOL_JEV_ENABLED=false` disables tool review.

## User And Session Isolation

The app is single-user and identifies conversations by `session_id`. `MEMORY_USER_ID` (default `default_user`) scopes memory:

- cognee session ids are `<user>__<session>`, sanitised with a hash suffix so distinct ids can never collide.
- The default user's main graph is `MEMORY_COGNEE_DATASET`; any other user id gets `<dataset>_<user>`.
- A merge only ever bridges its own session id.

## Durable Memory Jobs

| Job type | Handler | Purpose |
|---|---|---|
| `summary_generation` | `SummaryGenerationJobHandler` | Short-term summary blocks (secondary LLM) |
| `memory_session_write` | `MemorySessionWriteJobHandler` | Add a worth-storing turn to the cognee session; schedule the idle merge |
| `memory_session_merge` | `MemorySessionMergeJobHandler` | Merge an idle session into the main graph |
| `cognee_ingest` | `CogneeIngestJobHandler` | Explicit writes (API, backfill) straight into the main graph |

The queue (`memory_jobs`, `src/memory/job_repository.py`) provides idempotency keys, delayed `available_at`, retries with backoff, dead letters, and stale-job recovery. The API starts the worker in-process (`src/memory/worker_runtime.py`); chat never runs jobs inline. When cognee is disabled or not installed, cognee jobs fail as non-retryable so the problem is visible in dead letters.

## Short-Term Summaries

Unchanged. `src/memory/token_budget.py`, `src/memory/summary_blocks.py`, and `src/memory/short_term.py` keep raw turns and immutable summary blocks inside the context budget, with summaries generated by background `summary_generation` jobs.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `JEV_ENDPOINT` | (empty) | OpenAI-compatible base URL, e.g. `http://localhost:8001/v1` |
| `JEV_MODEL` | (empty) | Model name at that endpoint |
| `JEV_API_KEY` | (empty) | Bearer key, read at call time and never exposed by the API |
| `JEV_TIMEOUT_SECONDS` | `5` | Per-decision timeout |
| `TOOL_JEV_ENABLED` | `true` | Jev review of medium-risk tool calls |
| `COGNEE_ENABLED` | `true` | Long-term memory on/off |
| `MEMORY_STORAGE_ENABLED` | `true` | Allow session writes |
| `MEMORY_RETRIEVAL_ENABLED` | `true` | Allow main-graph recall |
| `SESSION_IDLE_TIMEOUT` | `30` | Minutes of inactivity before a session merges |
| `MEMORY_USER_ID` | `default_user` | Memory scope (letters, digits, `_`, `-`) |
| `MEMORY_COGNEE_DATASET` | `ivo_memory` | Main graph dataset |
| `MEMORY_COGNEE_DATA_DIR` | `.agent/cognee` | cognee storage |
| `MEMORY_COGNEE_SEARCH_TYPE` | `SUMMARIES` | `SUMMARIES`, `CHUNKS`, `GRAPH_COMPLETION`, or `RAG_COMPLETION` |
| `MEMORY_COGNEE_TOP_K` | `8` | Maximum recalled snippets |
| `MEMORY_COGNEE_RECALL_TIMEOUT_SECONDS` | `8` | Recall timeout |
| `MEMORY_COGNEE_RETRIEVAL_TOKEN_BUDGET` | `1500` | Token cap for the injected block |

cognee's own LLM and embedding settings (`LLM_*`, `EMBEDDING_*`) are read by cognee; `LLM_API_KEY` and `EMBEDDING_API_KEY` default to `OPENAI_API_KEY`. cognee 1.x also reads the project `.env` directly, and its values take precedence over process environment variables.

## Observability

Structured, content-free log events (logger `ivo.memory`, `src/memory/events.py`):

| Event | Fields |
|---|---|
| `memory.store.decision` | user_id, session_id, decision, source (`jev`/`rule`/`fallback`), latency_ms, error_category |
| `memory.retrieve.decision` | same |
| `memory.session.write` | user_id, session_id, success, latency_ms, error_category |
| `memory.session.merge` | user_id, session_id, success, outcome, latency_ms, error_category |
| `memory.retrieve` | user_id, session_id, success, hits, latency_ms, error_category |
| `tool.route.decision` | session_id, tool_name, risk_class, requires_approval, source, latency_ms, error_category |

No user text, tool arguments, or recalled content is logged.

Read-only endpoints live under `/api/memory/observability/*`; `GET /api/memory/observability/long-term` reports cognee availability, Jev status (configured, model, tool review), and per-job-type pipeline counts. See [Memory Observability API](api-memory-observability.md).

## Table Ownership

| Table | Owner |
|---|---|
| `raw_turns` | Short-term chat history; also the idle-activity signal |
| `summary_blocks` | Immutable summaries |
| `memory_jobs` | Durable queue; session write/merge history |
| `dead_letter_jobs` | Exhausted worker failures |
| `worker_heartbeats` | Worker status |
| `approval_requests` | HITL approvals, including Jev escalations |

Long-term knowledge lives in cognee's stores under `.agent/cognee`, not in SQLite.

## Legacy Compatibility

The pre-cognee tables (`facts`, `episodes`, `structured_episodes`, `pending_fact_candidates`, `semantic_embeddings`, `semantic_dedup_events`, `consolidation_runs`, `memory_entities`, `skills`, `skill_candidates`, `skill_versions`, `skill_usage_stats`, `procedural_skill_approvals`) are still created by schema migrations and readable in the Data Inspector. Nothing writes to them. `python -m src.memory.cognee_backfill` imports them once into the main graph; see [Legacy Memory Backfill](legacy-memory-backfill.md).

## Known Limitations

- **Session writes need embeddings.** cognee 1.6 saves a session entry and then embeds it for session recall. If the embedding provider is down, that step fails open only after a minute or two of retries, so each session write can occupy the single memory worker that long. The write timeout is 300 seconds so the fail-open completes; a write cut off later than that is retried and can duplicate the session entry.
- **Merges need cognee's LLM.** `improve()` extracts graph knowledge with cognee's configured LLM (`LLM_API_KEY` etc.). Without one, merges retry and then dead-letter; force-merge after fixing the provider.
- **Storage decisions are not carried across HITL resumes.** A turn paused for approval is not stored when it resumes, because the resumed run has no new user message for Jev to judge.
- **Single-user identity.** Memory is scoped by `MEMORY_USER_ID`; the chat API has no per-request user, so all sessions in one deployment share that user's main graph.
- **The retrieval trace bypasses Jev.** It shows what recall would return, not whether Jev would have asked for it.
