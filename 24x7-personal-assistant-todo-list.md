# Todo List: Build 24x7 Personal Assistant (Backend Core & Harness)

Status: Active Development Task Checklist
Based on: `24x7-personal-assistant-production-blueprint.md` & `waku-agent` architecture insights.
Target Scope: Backend Harness, SQLite + FTS5 Engine, Personal OS Tools, MCP Gateway, HITL Governance.

---

## 0. Architecture & Core Assumptions

- [x] Use standard Python runtime for agent harness loop (`while not done: reason -> act -> observe -> reply`).
- [x] Use SQLite (`state.db`) with `fts5` full-text search as the unified database engine (no heavy vector DB dependencies).
- [x] Maintain `.agent/MEMORY.md` as an auto-synced, human-readable mirror of semantic facts from SQLite `facts` table.
- [x] Enforce Tool-Based Human-In-The-Loop (HITL) risk governance—never rely on LLM self-evaluations for safety gates.
- [x] Execute remote code and web browsing inside third-party isolated execution sandboxes.

---

## 1. System Prompt & Harness Foundation

### System Prompt (`SOUL.md`)
- [x] Create `.agent/SOUL.md` master system prompt.
- [x] Define assistant identity, tone, guidelines, operational principles, and behavioral boundaries.
- [x] Implement system prompt context loader into the LLM context wrapper.

### Short-Term Memory (Chat History Thread)
- [x] Implement working chat history thread buffer (`messages` list).
- [x] Implement context window monitor (token counter).
- [x] Implement automatic message trimming & text summarization when context limits are reached.
- [x] Preserve system prompt (`SOUL.md`) and ongoing task state across summarization sweeps.

---

## 2. Long-Term Memory System (SQLite + FTS5)

### Database Setup
- [x] Initialize SQLite database (`.agent/state.db`).
- [x] Create `fts5` virtual table `episodes` (id, session_id, timestamp, content, tool_calls, outcome).
- [x] Create `fts5` virtual table `facts` (id, category, fact_text, source, confidence, created_at).
- [x] Create SQLite table `skills` (id, name, description, trigger_keywords, execution_steps).
- [x] Create SQLite table `checkpoints` (id, task_id, state_json, created_at).

### 2.1 Episodic Memory (RAG + SQL)
- [x] Implement episodic logger to store turn events, tool calls, and task results in `episodes`.
- [x] Implement FTS5 keyword RAG search helper for historic conversation episodes.

### 2.2 Semantic Memory (Keyword Top-K & `MEMORY.md` Sync)
- [x] Implement keyword Top-K search over SQLite `facts` FTS5 table (no vector embeddings required).
- [x] Implement post-turn fact extraction worker (identifies user preferences, profile facts, decisions).
- [x] Implement auto-sync engine to render SQLite `facts` into `.agent/MEMORY.md`.

### 2.3 Procedural Memory (`SKILL.md`)
- [x] Create `.agent/SKILL.md` procedural memory catalog.
- [x] Implement skill selector matching user query triggers to stored procedures in `skills`.

### 2.4 Retrieval Gate
- [x] Implement Retrieval Gate classifier/heuristic.
- [x] Skip RAG retrieval on math, pure code generation, or trivial greetings.
- [x] Execute RAG retrieval when query references prior sessions, facts, or context.

---

## 3. Agent Orchestration (`spawn_agent()`)

- [x] Implement `spawn_agent()` tool function to launch isolated sub-agent processes.
- [x] Implement sub-agent context isolation (sub-agent receives scoped prompt and tool definitions).
- [x] Build sub-agent state registry to track active sub-agents.
- [x] Implement asynchronous parent-child agent communication channel.

---

## 4. MCP Tool Gateway & Sandbox Environments

### 4.1 Communication MCP
- [x] Implement Email MCP client (Read inbox, Search, Draft email, Send email [High Risk]).
- [x] Implement WhatsApp MCP integration wrapper.
- [x] Implement Telegram Bot MCP gateway (Receive messages, Send responses).

### 4.2 Calendar MCP
- [x] Implement Calendar MCP tools (`calendar_inspect_availability`, `calendar_propose_event`, `calendar_create_event`).

### 4.3 Search MCP
- [x] Implement Web Search API tool (`search_web`) using Tavily / DuckDuckGo returning structured citations.

### 4.4 Isolated Execution Environments
- [x] **4.4.1 Remote Code Execution Sandbox**:
  - [x] Implement sandboxed python/bash execution connector.
  - [x] Configure local host filesystem isolation.
  - [x] Add GitHub integration (clone repository, commit, push, create pull request).
- [x] **4.4.2 Web Browsing Sandbox**:
  - [x] Implement headless Playwright browser container connector.
  - [x] Extract DOM content into sanitized text/Markdown.
  - [x] Implement screenshot capture support.

---

## 5. Personal OS Tools (Native Core)

Implement 22 native Personal OS system tools:

### Task Management
- [x] Implement `create_task(title, description, priority)`
- [x] Implement `update_task(task_id, status, progress)`
- [x] Implement `cancel_task(task_id)`
- [x] Implement `list_tasks(status_filter)`

### Agent Orchestration & Lifecycle
- [x] Implement `spawn_agent(role, instructions, allowed_tools)`
- [x] Implement `terminate_agent(agent_id)`
- [x] Implement `pause_agent(agent_id)`
- [x] Implement `resume_agent(agent_id)`
- [x] Implement `get_agent_status(agent_id)`

### Scheduling & System Health
- [x] Implement `schedule_job(cron_or_timestamp, task_payload)`
- [x] Implement `cancel_job(job_id)`
- [x] Implement `heartbeat()`

### Resource & Concurrency Control
- [x] Implement `lock_resource(resource_uri)`
- [x] Implement `unlock_resource(resource_uri)`

### Event Bus
- [x] Implement `publish_event(topic, payload)`
- [x] Implement `subscribe_event(topic, handler)`

### Memory & Execution Context
- [x] Implement `acquire_context(query_or_topic)`
- [x] Implement `release_context(context_id)`

### Checkpointing & Recovery
- [x] Implement `checkpoint(task_id)`
- [x] Implement `restore_checkpoint(checkpoint_id)`

### Execution Flow Control
- [x] Implement `sleep(duration_seconds)`
- [x] Implement `wake(agent_id)`

---

## 6. Human-In-The-Loop (HITL) & Tool Safety Policy

### 6.1 Tool-Based Risk Classifier
- [x] Build deterministic risk classification evaluator (classifies actions based on tool name & parameters).
- [x] Classify low-risk tools (read-only, local context, internal task updates) -> Auto-execute.
- [x] Classify medium-risk tools (scheduling, internal agent spawns, reading emails) -> Auto-execute + Log.
- [x] Classify High-Risk operations requiring mandatory user approval:
  - [x] `bank_transfer` / Spend money
  - [x] `production_deploy` / Deploy code
  - [x] `delete_database` / Purge state
  - [x] `send_email` / Outbound communication
  - [x] `delete_files` / File deletion
  - [x] `github_merge` / Merge or push to main
  - [x] `spend_money` / Paid API transactions

### 6.2 Approval & Interrupt Engine
- [x] Implement graph interrupt mechanism on High-Risk tool detection.
- [x] Implement automatic `checkpoint()` save before pausing execution.
- [x] Generate structured approval request payload (tool name, parameters, diff, risk reason).
- [x] Build Approval Handler API (Approve / Reject decision processing).
- [x] On Approval: Invoke `restore_checkpoint()`, execute tool, and resume agent loop.
- [x] On Rejection: Abort tool execution and return user cancellation feedback to agent loop.

---

## 7. Verification & End-to-End Testing

- [x] **Unit Tests**: Test SQLite FTS5 table operations and `MEMORY.md` sync.
- [x] **Retrieval Gate Tests**: Verify memory retrieval is skipped for math/code queries and invoked for personal memory queries.
- [x] **Tool Gateway Tests**: Verify tool schema validation, error envelopes, and sandbox isolation.
- [x] **Personal OS Tool Tests**: Verify all 22 native tools function correctly within the harness.
- [x] **HITL Policy Tests**: Verify high-risk tools (`send_email`, `delete_database`, `bank_transfer`, `github_merge`) trigger state checkpointing and pause execution for human approval.
- [x] **Multi-Step Loop Test**: Test multi-turn task execution (`reason -> tool call -> observe -> consolidate`).

---

## 8. Stage 4: Advanced Architecture & Memory Subsystems Improvements

### 8.1 Primary & Secondary Tiered LLM Architecture
- [x] Configure Primary LLM (Planner / Reasoner / Tool Execution / Response) and track context window size capacity.
- [x] Configure Secondary LLM (Cheaper Model) for background async operations (Episodic Summary, Fact Extraction, Consolidation, Reflection, Deduplication).
- [x] Register Model Pairs from `models.pdf`:
  - [x] OpenAI: `GPT-5.5` / `GPT-5` (Primary) + `GPT-5 nano` (Secondary) [Fallback: `gpt-4o` + `gpt-4o-mini`].
  - [x] Anthropic: `Claude Opus 4.1` / `Claude Sonnet 4` (Primary) + `Claude Sonnet 4` (Secondary) [Fallback: `claude-3-5-sonnet-latest` + `claude-3-5-haiku-latest`].
  - [x] Google: `Gemini 2.5 Pro` / `Gemini 2.5 Flash` (Primary) + `Gemini 2.5 Flash-Lite` (Secondary) [Fallback: `gemini-1.5-pro` + `gemini-1.5-flash`].

### 8.2 Short-Term Memory Budgeting & Compaction
- [x] Enforce 25% context budget reservation for System Prompt (`SOUL.md`), retrieval context, and instructions.
- [x] Implement context compaction rules on remaining 75% budget based on model capacity:
  - [x] 128k/200k context models -> summarize oldest 30% messages.
  - [x] 400k context models -> summarize oldest 25% messages.
  - [x] 1M+ context models -> summarize oldest 20% messages.
- [x] Store uncompacted complete raw conversation turns in SQLite DB (`raw_turns` table).
- [x] Implement past conversation thread fetch API endpoint (`thread_id` / `session_id`).

### 8.3 Episodic Memory Detector & Structured Summary
- [x] Implement deterministic Episode Detector rules (`task_completed`, `workflow_finished`, `conversation_idle > 45m`, `trimming_occurred`, `conversation_tokens > 50_000`).
- [x] Implement Secondary LLM structured JSON output for episodic summaries (`title`, `summary`, `participants`, `goals`, `decisions`, `artifacts`, `topics`, `importance`).
- [x] Support multiple episodic memories per thread in SQLite `episodes`.

### 8.4 Semantic Memory Confidence Gate & Periodic Consolidation
- [x] Add `fact_candidates: list[FactCandidate]` to `AgentState` schema.
- [x] Implement confidence gate (`confidence > 0.90` -> save directly to semantic memory; else -> `pending_queue`).
- [x] Implement periodic consolidation worker (triggered after every 10 episodes) to search episodes & `pending_queue`, merge, update, and de-duplicate facts.

### 8.5 Procedural Memory Integration
- [x] Implement User-driven skills management (aligned with `waku-agent/waku/memory/procedural` patterns).

---

## Production Hardening & Full Agent Loop (Phases 1 - 7 Complete)

### Phase 1: Make Existing App Actually Coherent
- [x] Add missing backend endpoint: `GET /api/tasks`.
- [x] Add missing backend endpoint: `DELETE /api/scheduled/{job_id}`.
- [x] Fix frontend approval response mismatch: frontend expects `pending_approvals`, backend returns `approval_requests`.
- [x] Fix Tools UI risk field mismatch: frontend uses `t.risk`, backend returns `risk_level`.
- [x] Add a basic startup command/documentation: backend + frontend run path.
- [x] Add `pyproject.toml` or equivalent packaging so tests/imports work without manual PYTHONPATH.

### Phase 2: Build The Real Agent Loop
- [x] Replace the single LLM call in `src/harness/graph.py` with a true loop: `reason -> tool call -> risk check -> execute tool -> observe -> reason again -> final reply`.
- [x] Bind Personal OS tools and MCP tools to the LLM.
- [x] Add max-iteration guardrail.
- [x] Store every loop step in SQLite: LLM call, tool call, tool result, final answer.
- [x] Return loop metadata to frontend: iterations, tools used, retrieval decision, approval state.

### Phase 3: Make HITL Work On Real Tool Calls
- [x] Move HITL checking from keyword detection to actual proposed tool calls.
- [x] Before executing any high-risk tool, create checkpoint + approval request.
- [x] After approval, resume the saved tool call with its original arguments.
- [x] After rejection, feed rejection back into the agent as an observation.
- [x] Add frontend approval refresh and clear status after decision.

### Phase 4: Make Tools Real Enough
- [x] Implement real calendar storage first using SQLite/local calendar table.
- [x] Replace canned `search_web` response with Tavily or DuckDuckGo provider.
- [x] Replace email mocks with draft/read/send adapters, keeping send behind HITL.
- [x] Replace Telegram/WhatsApp mocks only after email/calendar/search are stable.
- [x] Replace browser mock with Playwright-based page fetch/screenshot.
- [x] Harden `run_code` sandbox or clearly mark it local/dev-only.

### Phase 5: Make The Frontend A Real Cockpit
- [x] Add Waku-style Overview tab showing: retrieval gate, loop status, tool calls, memory writes.
- [x] Add Loop tab with per-turn timeline.
- [x] Add Data tab for read-only SQLite table browsing.
- [x] Add Memory tabs for semantic, episodic, procedural memory.
- [x] Add Tool results/history panel.
- [x] Add chat history with session rename/delete.
- [x] Remove CDN/Babel frontend runtime and use proper Vite build.

### Phase 6: Database/Product Reliability
- [x] Add database migrations/versioning.
- [x] Add explicit schemas for chat turns, loop events, tool calls, tool results.
- [x] Add scheduled job runner, not just job registration.
- [x] Add background worker process for consolidation/scheduled jobs.
- [x] Add graceful startup: initialize `.agent`, DB, `SOUL.md`, `MEMORY.md`, `SKILL.md`.
- [x] Add export/backup for `.agent/state.db` and memory files.

### Phase 7: Test Real Behavior
- [x] Add integration test for chat -> tool call -> tool result -> final reply.
- [x] Add HITL test using actual high-risk tool call, not keyword detection.
- [x] Add API contract tests for every frontend endpoint.
- [x] Add frontend smoke test: load page, send message, see response.
- [x] Add database persistence test across app restart.
- [x] Add test for scheduled job execution.

### Phase 10: Verification Audit & Fix Plan
- [x] Fix `github_clone()` in `src/mcp_gateway/sandboxes/code_sandbox.py` so non-zero git exit codes return `FAILED` instead of treating `"already exists"` in `stderr` as success.
- [x] Add workspace boundary validation in `github_clone()` ensuring `target_dir` stays within `.agent/workspace/`.
- [x] Make `test_github_tools_return_structured_failures()` in `tests/test_p1_integration_truthfulness.py` deterministic by using pytest `tmp_path`.
- [x] Remove duplicate `POST /api/system/backup` endpoint declaration in `src/api/server.py`.
- [x] Add missing `playwright>=1.40.0` and `duckduckgo-search>=4.0.0` dependencies to `pyproject.toml`.
- [x] Update `README.md` test count claim to match actual verified 100% passing test result.
- [x] Re-run `python -m pytest -q -p no:cacheprovider` to verify 0 failed tests (178 passed, 3 skipped).
- [x] Re-run `cd frontend && npm run build` to verify clean production static build in `frontend/dist/`.


