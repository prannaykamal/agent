# Tools Architecture Gap Analysis

Generated from the current repository state in `D:\agent`.

## Executive Summary

The completed memory architecture provides durable jobs, role-separated LLM routing, HITL approvals, observability, versioned procedural skills, and adaptive retrieval. The current tools architecture predates that work and is not yet aligned with it.

The largest gap is that the codebase labels many local adapters as "MCP" tools, but most target MCP integrations are not provider-managed MCP tools today. Search, calendar, email, WhatsApp, and Telegram are implemented locally in `src/mcp_gateway/*` through SQLite, REST, SMTP, IMAP, or fallback adapters. The repository does contain an MCP protocol bridge, but the configured `.agent/mcp_config.json` currently references a filesystem server and a mock/fetch SSE server, not the target provider set.

Browser sandbox and code sandbox are hard-wired into the MCP registry, API routes, integration status, tests, dependencies, and docs. They should be removed completely, but no tracked runtime file is safe to delete immediately without reference cleanup.

Personal OS exists as 22 LangChain tools, but it is a broad local tool layer with direct SQLite writes, minimal policy metadata, no memory-aware design, and no consistent observability boundary. It should be redesigned around the completed memory architecture rather than patched incrementally.

The cron-job tool exists as `schedule_job`, `cancel_job`, and a polling worker over `scheduled_jobs`, but it is incomplete: recurrence is not implemented, cron expressions are compared as timestamps, missed jobs are not handled, timezones are not modeled, and due jobs are marked completed without executing structured actions.

## Scope and Method

Inspected areas:

- `src/`
- `src/mcp_gateway/`
- `src/personal_os/`
- `src/harness/`
- `src/api/`
- `src/memory/`
- `src/hitl/`
- `src/startup.py`
- `frontend/src/`
- `tests/`
- `docs/`
- `requirements.txt`
- `pyproject.toml`
- `.env.example`
- `.agent/mcp_config.json`

This document is analysis only. No code was implemented, no files were deleted, and runtime behavior was not changed.

## 1. Current Tool Inventory

### Personal OS Tools

All Personal OS tools are registered in `src/personal_os/registry.py` and exposed to the agent through `src/harness/graph.py:get_registered_tools()`. The API exposes their catalog through `GET /api/tools`. Some also have direct REST endpoints.

| Tool | File | MCP or non-MCP | Agent exposed | API/frontend exposed | Capability | Approval today | Memory-aware | Tested | Recommendation |
|---|---|---:|---:|---:|---|---|---|---|---|
| `create_task` | `src/personal_os/tasks.py` | Non-MCP | Yes | API via `/api/tasks` read only, catalog UI | Write local task | No | No | Yes | Migrate |
| `update_task` | `src/personal_os/tasks.py` | Non-MCP | Yes | Catalog UI | Write local task | No | No | Yes | Migrate |
| `cancel_task` | `src/personal_os/tasks.py` | Non-MCP | Yes | Catalog UI | Write local task | No | No | Yes | Migrate |
| `list_tasks` | `src/personal_os/tasks.py` | Non-MCP | Yes | `/api/tasks`, catalog UI | Read local task | No | No | Yes | Preserve then redesign |
| `spawn_agent` | `src/orchestration/tools.py` | Non-MCP | Yes | `/api/tasks` shows sub-agents, catalog UI | Launch sub-agent | Medium risk only in classifier | No | Yes indirectly | Migrate with stricter policy |
| `terminate_agent` | `src/personal_os/agent_lifecycle.py` | Non-MCP | Yes | Catalog UI | Write sub-agent status | No | No | Yes | Migrate |
| `pause_agent` | `src/personal_os/agent_lifecycle.py` | Non-MCP | Yes | Catalog UI | Write sub-agent status | No | No | Yes | Migrate |
| `resume_agent` | `src/personal_os/agent_lifecycle.py` | Non-MCP | Yes | Catalog UI | Write sub-agent status | No | No | Yes | Migrate |
| `get_agent_status` | `src/personal_os/agent_lifecycle.py` | Non-MCP | Yes | Catalog UI | Read sub-agent status | No | No | Yes | Preserve then redesign |
| `schedule_job` | `src/personal_os/scheduling.py` | Non-MCP | Yes | `/api/scheduled`, Scheduled UI | Write scheduled job | Medium risk in classifier, not HITL-gated by API | No | Yes | Fix |
| `cancel_job` | `src/personal_os/scheduling.py` | Non-MCP | Yes | `/api/scheduled`, Scheduled UI | Write scheduled job | No | No | Yes | Fix |
| `heartbeat` | `src/personal_os/scheduling.py` | Non-MCP | Yes | Catalog UI, health adjacent | Read DB clock | No | No | Yes | Preserve |
| `lock_resource` | `src/personal_os/concurrency.py` | Non-MCP | Yes | Catalog UI | Write lock | No | No | Yes | Redesign |
| `unlock_resource` | `src/personal_os/concurrency.py` | Non-MCP | Yes | Catalog UI | Delete lock | No | No | Yes | Redesign |
| `publish_event` | `src/personal_os/event_bus.py` | Non-MCP | Yes | Catalog UI | Write event | No | No | Yes | Redesign |
| `subscribe_event` | `src/personal_os/event_bus.py` | Non-MCP | Yes | Catalog UI | No persistent subscription | No | No | Yes | Replace or remove |
| `acquire_context` | `src/personal_os/context.py` | Non-MCP | Yes | Catalog UI | Write synthetic context block | No | Not integrated with memory retrieval | Yes | Replace |
| `release_context` | `src/personal_os/context.py` | Non-MCP | Yes | Catalog UI | Update context block | No | Not integrated with memory retrieval | Yes | Replace |
| `checkpoint` | `src/personal_os/checkpointing.py` | Non-MCP | Yes | Used by HITL | Write checkpoint | No | No | Yes | Preserve then refactor |
| `restore_checkpoint` | `src/personal_os/checkpointing.py` | Non-MCP | Yes | Catalog UI | Read checkpoint | No | No | Yes | Preserve then refactor |
| `sleep` | `src/personal_os/execution_control.py` | Non-MCP | Yes | Catalog UI | Synchronous delay simulation | No | No | Yes | Replace |
| `wake` | `src/personal_os/execution_control.py` | Non-MCP | Yes | Catalog UI | Synthetic wake response | No | No | Yes | Replace |

### Local MCP Gateway Tools

These are registered in `src/mcp_gateway/registry.py` as static LangChain tools and then combined with optional live MCP tools from `src/mcp_gateway/mcp_bridge.py`. Most should not remain as custom provider implementations in the target architecture.

| Tool | File | MCP or non-MCP today | Agent exposed | API/frontend exposed | Capability | Approval today | Memory-aware | Tested | Recommendation |
|---|---|---:|---:|---:|---|---|---|---|---|
| `email_read` | `src/mcp_gateway/communication.py` | Local adapter labeled MCP | Yes | `/api/email/messages`, catalog UI | Read IMAP or SQLite | No | No | Yes | Replace with Gmail MCP wiring |
| `email_search` | `src/mcp_gateway/communication.py` | Local adapter labeled MCP | Yes | Catalog UI | Read SQLite email | No | No | Yes | Replace with Gmail MCP wiring |
| `email_draft` | `src/mcp_gateway/communication.py` | Local adapter labeled MCP | Yes | `/api/email/draft`, catalog UI | Write SQLite draft | No | No | Yes | Replace with Gmail MCP wiring and approval policy |
| `email_send` | `src/mcp_gateway/communication.py` | Local SMTP/SQLite adapter labeled MCP | Yes | `/api/email/send`, catalog UI | External communication/write SQLite | High risk via graph/API approval | No | Yes | Replace with Gmail MCP wiring |
| `whatsapp_read` | `src/mcp_gateway/communication.py` | Local SQLite adapter labeled MCP | Yes | Catalog UI/status only | Read SQLite messages | No | No | Yes | Replace with WhatsApp MCP wiring |
| `whatsapp_send` | `src/mcp_gateway/communication.py` | Local Meta REST/SQLite adapter labeled MCP | Yes | Catalog UI/status only | External communication/write SQLite | High risk in graph only | No | Yes | Replace with WhatsApp MCP wiring |
| `telegram_read` | `src/mcp_gateway/communication.py` | Local SQLite adapter labeled MCP | Yes | Catalog UI/status only | Read SQLite messages | No | No | Yes | Replace with Telegram MCP wiring |
| `telegram_send` | `src/mcp_gateway/communication.py` | Local Telegram REST/SQLite adapter labeled MCP | Yes | Catalog UI/status only | External communication/write SQLite | High risk in graph only | No | Yes | Replace with Telegram MCP wiring |
| `calendar_inspect_availability` | `src/mcp_gateway/calendar.py` | Local SQLite adapter labeled MCP | Yes | `/api/calendar/events` read, catalog UI | Read calendar_events | No | No | Yes | Replace with Google Calendar MCP wiring |
| `calendar_propose_event` | `src/mcp_gateway/calendar.py` | Local SQLite adapter labeled MCP | Yes | Catalog UI | Write tentative local event | No | No | Yes | Replace or redesign as local draft/approval helper |
| `calendar_create_event` | `src/mcp_gateway/calendar.py` | Local SQLite plus optional Google REST | Yes | `/api/calendar/events` POST approval, catalog UI | External calendar write | High risk via graph/API approval | No | Yes | Replace with Google Calendar MCP wiring |
| `calendar_update_event` | `src/mcp_gateway/calendar.py` | Local SQLite adapter labeled MCP | Yes | `/api/calendar/events/{id}` PUT direct, catalog UI | External/local calendar write | Incorrectly classified Low in MCP risk map, no REST approval | No | Yes | Replace and fix policy |
| `calendar_delete_event` | `src/mcp_gateway/calendar.py` | Local SQLite adapter labeled MCP | Yes | `/api/calendar/events/{id}` DELETE approval, catalog UI | External/local calendar delete | High risk via classifier, Low in MCP risk map | No | Yes | Replace and fix policy |
| `search_web` | `src/mcp_gateway/search.py` | Local Tavily/DuckDuckGo adapter labeled MCP | Yes | `/api/search`, catalog UI | External read | No | No | Yes | Replace with Tavily/DuckDuckGo MCP wiring |
| `run_code` | `src/mcp_gateway/sandboxes/code_sandbox.py` | Local code sandbox | Yes | Catalog UI | Executes local Python | Classified Low | No | Yes | Delete |
| `github_clone` | `src/mcp_gateway/sandboxes/code_sandbox.py` | Local code/git sandbox | Yes | `/api/github/clone`, catalog UI/status | Subprocess/git write potential | Classified Low | No | Yes | Delete with code sandbox |
| `github_commit_and_push` | `src/mcp_gateway/sandboxes/code_sandbox.py` | Local code/git sandbox | Yes | `/api/github/commit_and_push`, catalog UI/status | Git write/push | Medium | No | Yes | Delete with code sandbox |
| `github_merge` | `src/mcp_gateway/sandboxes/code_sandbox.py` | Local code/git sandbox | Yes | `/api/github/merge`, catalog UI/status | Git merge | High | No | Yes | Delete with code sandbox |
| `safe_browse_url` | `src/mcp_gateway/sandboxes/browser_sandbox.py` | Local browser sandbox | Yes | `/api/browser/browse`, catalog UI/status | External fetch | Classified Low | No | Yes | Delete |
| `capture_screenshot` | `src/mcp_gateway/sandboxes/browser_sandbox.py` | Local browser sandbox | Yes | `/api/browser/screenshot`, catalog UI/status | External fetch/file write | Classified Low | No | Yes | Delete |
| Dynamic live MCP tools | `src/mcp_gateway/mcp_bridge.py` | Actual MCP wrapper | Yes when loaded | Catalog UI | Depends on provider | Default Low if no risk metadata | No | Protocol tests only | Preserve and harden |

### Current MCP Protocol Infrastructure

| Component | File | Current State | Recommendation |
|---|---|---|---|
| MCP JSON-RPC client | `src/mcp_gateway/protocol/client.py` | Implements initialize, tools/list, tools/call | Preserve and harden |
| Stdio transport | `src/mcp_gateway/protocol/transports/stdio.py` | Launches subprocess MCP server | Preserve, add safer lifecycle/observability |
| SSE transport | `src/mcp_gateway/protocol/transports/sse.py` | Test-oriented simulated SSE responses | Replace with real SSE/streamable HTTP behavior if required |
| Bridge/wrapper | `src/mcp_gateway/mcp_bridge.py` | Reads `.agent/mcp_config.json`, creates LangChain tools | Refactor into discovery/registration/routing boundary |
| MCP config | `.agent/mcp_config.json` | Configures `filesystem` and `fetch_sse`; no target providers | Replace with provider configs or app-managed discovery |

## 2. Browser Sandbox Removal Analysis

### Files

- `src/mcp_gateway/sandboxes/browser_sandbox.py`
- `src/mcp_gateway/sandboxes/__init__.py` if no remaining sandbox package users exist after code sandbox removal
- Generated caches under `src/mcp_gateway/sandboxes/__pycache__/` if present

### Imports and References

- `src/mcp_gateway/registry.py` imports `safe_browse_url` and `capture_screenshot`, registers both in `ALL_MCP_TOOLS`, and marks both Low risk.
- `src/api/server.py` imports `safe_browse_url` and `capture_screenshot`.
- `src/api/server.py` exposes:
  - `POST /api/browser/browse`
  - `POST /api/browser/screenshot`
- `src/api/server.py` reports `"browser"` in `GET /api/integrations/status`.
- Tests import or assert browser sandbox behavior:
  - `tests/test_p4_browser.py`
  - `tests/test_mcp_gateway.py`
  - `tests/test_real_tools.py`
  - `tests/test_p7_product_readiness.py`
  - `tests/test_p1_integration_truthfulness.py`
- Docs mention Playwright/browser sandbox:
  - `docs/ARCHITECTURE.md`
  - `docs/implementation-roadmap.md`
- Dependencies:
  - `requirements.txt`: `playwright>=1.40.0`
  - `pyproject.toml`: `playwright>=1.40.0`

### Safe Delete Assessment

Not safe to delete immediately. The browser sandbox has live imports in `src/mcp_gateway/registry.py` and `src/api/server.py`; deleting the file first would break application import and API startup.

### Required Cleanup Before Deletion

1. Remove browser tools from `ALL_MCP_TOOLS` and risk maps.
2. Remove browser API routes and request models from `src/api/server.py`.
3. Remove browser integration status card.
4. Remove or migrate browser-specific tests.
5. Remove Playwright dependency if frontend/e2e tests do not still require it.
6. Update docs that advertise browser sandbox behavior.

## 3. Code Sandbox Removal Analysis

### Files

- `src/mcp_gateway/sandboxes/code_sandbox.py`
- `src/mcp_gateway/sandboxes/__init__.py` if no remaining sandbox package users exist after browser sandbox removal
- Generated caches under `src/mcp_gateway/sandboxes/__pycache__/` if present

### Imports and References

- `src/mcp_gateway/registry.py` imports and registers:
  - `run_code`
  - `github_clone`
  - `github_commit_and_push`
  - `github_merge`
- `src/api/server.py` imports GitHub sandbox functions.
- `src/api/server.py` exposes:
  - `POST /api/github/clone`
  - `POST /api/github/commit_and_push`
  - `POST /api/github/merge`
- `src/api/server.py` reports `"github"` integration status as real subprocess tooling.
- `src/hitl/classifier.py` classifies `github_merge` High and `github_commit_and_push` Medium.
- `src/hitl/approval_engine.py` has approval preview logic for `github_merge`.
- Tests import or assert code sandbox behavior:
  - `tests/test_mcp_gateway.py`
  - `tests/test_e2e.py`
  - `tests/test_p4_github.py`
  - `tests/test_p3_strengthen_hitl.py`
  - `tests/test_p6_security.py`
  - `tests/test_p1_integration_truthfulness.py`
  - `tests/test_p7_product_readiness.py`
  - `tests/test_hitl.py`

### Safe Delete Assessment

Not safe to delete immediately. It is imported by the MCP registry and API server. Several tests also depend on it.

### Required Cleanup Before Deletion

1. Remove code sandbox tools from MCP registry and catalog output.
2. Remove GitHub sandbox API routes or replace them with a separate approved GitHub connector design outside this target scope.
3. Remove GitHub sandbox integration status.
4. Remove code sandbox and GitHub sandbox risk entries unless replaced by a new provider-managed tool.
5. Delete or migrate tests that assert sandbox execution.
6. Update docs and dependencies.

## 4. Personal OS Tool Analysis

### Current Responsibilities

`src/personal_os/` currently covers:

- Task CRUD through `tasks`
- Scheduler rows through `scheduled_jobs`
- Agent lifecycle controls over `sub_agents`
- Resource locking through `resource_locks`
- Event publishing through `events_log`
- Context acquisition/release through `context_blocks`
- Checkpoint write/read through `checkpoints`
- Sleep/wake execution control
- Backup/restore helpers in `src/personal_os/backup.py`

### Current File Structure

- `src/personal_os/registry.py`
- `src/personal_os/tasks.py`
- `src/personal_os/scheduling.py`
- `src/personal_os/agent_lifecycle.py`
- `src/personal_os/concurrency.py`
- `src/personal_os/event_bus.py`
- `src/personal_os/context.py`
- `src/personal_os/checkpointing.py`
- `src/personal_os/execution_control.py`
- `src/personal_os/backup.py`

### Memory Awareness

Current Personal OS tools do not use:

- semantic memory
- structured episodic memory
- procedural skills
- memory_jobs
- summary blocks
- retrieval planner/context assembler
- memory observability

`acquire_context` writes synthetic context blocks instead of using the completed retrieval and memory architecture. `checkpoint` is used by HITL but stores a minimal synthetic JSON payload, not a full memory-aware execution state.

### HITL and Approval

Only `spawn_agent` and `schedule_job` are classified Medium in `src/hitl/classifier.py`. Most Personal OS write tools execute directly. There is no centralized policy based on:

- read/write scope
- filesystem scope
- external side effect
- scheduled future execution
- destructive update
- multi-agent lifecycle control

### Persistence

Personal OS uses legacy local tables:

- `tasks`
- `scheduled_jobs`
- `resource_locks`
- `events_log`
- `context_blocks`
- `checkpoints`
- `sub_agents`

It does not use `memory_jobs`. For Personal OS redesign, durable tool execution should use its own tool/task/scheduler persistence where appropriate, while memory enrichment and long-term learning should use memory architecture boundaries.

### Observability

Observability is partial:

- `loop_events`, `tool_calls`, `tool_results`, and `audit_logs` exist.
- `/api/tasks`, `/api/scheduled`, and `/api/tools` expose some state.
- There is no unified Personal OS operations panel, risk status, pending policy state, execution trace, or retry/failure view.

### Preserve, Redesign, Delete

Preserve:

- The concept of Personal OS as the local non-MCP tool layer.
- Durable task and scheduling concepts.
- Checkpointing/HITL linkage, after refactor.
- Audit tables, with redaction and better policy.

Redesign:

- Tool registry and metadata.
- Tool invocation boundary.
- Approval policy.
- Scheduler/cron semantics.
- Context and memory integration.
- Observability.
- Error handling and idempotency.

Delete or replace:

- Synthetic `sleep`/`wake` behavior.
- `subscribe_event` if it remains non-persistent.
- `acquire_context`/`release_context` as current synthetic context writers.

## 5. Cron-job Tool Analysis

### Current Implementation

- Tool functions: `src/personal_os/scheduling.py`
  - `schedule_job(cron_or_timestamp, task_payload)`
  - `cancel_job(job_id)`
  - `heartbeat()`
- Table: `scheduled_jobs` in `src/db.py`
  - `id`
  - `cron_or_timestamp`
  - `task_payload`
  - `status`
  - `created_at`
- Worker: `src/background_worker.py`
  - `process_due_scheduled_jobs()`
  - `run_scheduled_worker_loop()`
- API/UI:
  - `GET /api/scheduled`
  - `POST /api/scheduled`
  - `DELETE /api/scheduled/{job_id}`
  - `frontend/src/components/ScheduledCockpit.jsx`

### Findings

| Requirement | Current State | Gap |
|---|---|---|
| Jobs survive restart | Rows survive restart | Worker execution state is minimal; no next-run model |
| One-time jobs work | Timestamp strings can be marked due | Format is not validated and no structured action executes |
| Recurring jobs work | Cron string accepted | Cron expressions are compared lexicographically to timestamp strings |
| Missed jobs handled | No | No missed-run policy |
| Timezone handling | No explicit model | Uses local `datetime.now().strftime("%Y-%m-%d %H:%M")` |
| Google Calendar overlap | No clean boundary | Calendar events are separate local adapter, not provider MCP |
| Approval for scheduled actions | Partial | `schedule_job` Medium risk in classifier, REST endpoint executes directly |
| Execution | Poller marks due jobs `COMPLETED` | No actual routed action execution |
| Observability | Basic list endpoint/UI | No due/last run/next run/failure/dead-letter view |

### Memory Jobs or Separate Scheduler Table

Cron should use a separate scheduler table for schedule definitions and run history because schedule state is not memory processing state. However, when a scheduled action becomes due, the execution boundary should be explicit:

- For memory work, enqueue `memory_jobs`.
- For tool work, enqueue or claim a tool execution job with approval policy.
- For reminders or chat notifications, create a durable notification/action record.

Do not overload `memory_jobs` as a general scheduler table.

### Required Fixes

1. Split schedule definition from run attempts.
2. Parse and validate timestamp versus cron expression.
3. Store timezone, next_run_at, last_run_at, missed_run_policy, and recurrence state.
4. Route due actions through a policy-aware tool execution boundary.
5. Require approval at schedule creation and/or execution for high-risk future actions.
6. Add observability for pending, due, running, failed, cancelled, completed, and missed jobs.

## 6. MCP Tool Wiring Analysis

### Tavily / DuckDuckGo Search MCP

Current state:

- Local implementation in `src/mcp_gateway/search.py` and `src/mcp_gateway/search_adapters.py`.
- Uses `TAVILY_API_KEY` directly against Tavily REST API.
- Falls back to `duckduckgo_search.DDGS`.
- Falls back again to synthetic DuckDuckGo/doc URLs.
- Exposed to agent as `search_web`.
- Exposed through `GET /api/search`.
- Listed in `/api/tools`.
- Status in `/api/integrations/status`.

Gaps:

- Not configured as a provider-managed Tavily or DuckDuckGo MCP server.
- Local code reimplements provider behavior.
- No MCP provider discovery/credential state for Tavily/DuckDuckGo.
- No source-specific MCP observability.
- Tests validate local adapter, not MCP wiring.

Recommendation:

- Replace local search implementation with provider-managed MCP tool discovery and invocation.
- Keep only registration, routing, approval policy, observability, and error handling locally.
- Keep `/api/search` only if redefined as a thin read-only wrapper around the approved search MCP route.

### Google Calendar MCP

Current state:

- Local implementation in `src/mcp_gateway/calendar.py`.
- Stores events in SQLite `calendar_events`.
- Optional direct Google Calendar REST path uses `GOOGLE_CALENDAR_TOKEN`.
- `GoogleCalendarSyncProvider` in `src/mcp_gateway/google_calendar_sync.py` simulates push/pull when credentials exist.
- Exposed to agent and API.
- Create/delete use REST approval endpoints; update executes directly.

Gaps:

- Not wired to a provider-managed Google Calendar MCP.
- Local CRUD duplicates provider behavior.
- `calendar_update_event` is write-capable but is Low in `TOOL_RISK_MAP` and direct in API.
- Delete is Low in `TOOL_RISK_MAP` but High in classifier.
- Credential variables are inconsistent: `.env.example` lacks Google Calendar credentials even though code checks several names.
- Tests validate SQLite/local behavior, not MCP wiring.

Recommendation:

- Replace local CRUD implementation with Google Calendar MCP invocation.
- Preserve local read/cache tables only if explicitly needed as cache/audit, not as source-of-truth provider implementation.
- Correct approval policy for create, update, delete, attendee changes, and external invitations.

### WhatsApp MCP

Current state:

- Local implementation in `src/mcp_gateway/communication.py`.
- Reads/writes SQLite `whatsapp_messages`.
- Optionally sends through Meta Graph REST if `WHATSAPP_API_TOKEN` and `WHATSAPP_PHONE_NUMBER_ID` exist.
- No dedicated API route found except catalog/status/data inspector.
- Exposed to agent.

Gaps:

- Not provider-managed MCP.
- Local REST implementation duplicates provider behavior.
- No route-level HITL because no public route exists; graph HITL exists by name.
- No observability for MCP provider status or failures.
- `.env.example` lacks `WHATSAPP_PHONE_NUMBER_ID` despite code requiring it.

Recommendation:

- Replace local REST/SQLite send implementation with WhatsApp MCP route.
- Keep local tables only as optional audit/cache if target design approves.
- Require HITL for all outbound messages.

### Telegram MCP

Current state:

- Local implementation in `src/mcp_gateway/communication.py`.
- Reads/writes SQLite `telegram_messages`.
- Optionally sends through Telegram Bot API if `TELEGRAM_BOT_TOKEN` exists.
- No dedicated API route found except catalog/status/data inspector.
- Exposed to agent.

Gaps:

- Not provider-managed MCP.
- Local REST implementation duplicates provider behavior.
- No MCP credential/provider status.
- Tests validate local Bot API adapter behavior.

Recommendation:

- Replace local Telegram Bot REST implementation with Telegram MCP route.
- Require HITL for outbound messages.
- Keep read/cache storage only if explicitly needed and documented.

### Gmail MCP

Current state:

- Implemented as generic email tools over SMTP/IMAP in `src/mcp_gateway/communication.py` and `src/mcp_gateway/email_adapters.py`.
- `.env.example` references Gmail SMTP/IMAP host/user/password.
- Exposed to agent and API.

Gaps:

- No Gmail MCP server configuration.
- No Gmail OAuth/provider-managed permission model.
- Local SMTP/IMAP code duplicates provider behavior.
- Draft/write/send boundaries are not modeled as Gmail MCP capabilities.
- Tests validate SMTP/IMAP local mode, not Gmail MCP discovery/routing.

Recommendation:

- Replace SMTP/IMAP implementation with Gmail MCP tool discovery and invocation.
- Maintain API compatibility only through thin wrappers if needed.
- Require HITL for send and risky draft/update/delete actions.

## 7. Tool Routing Analysis

### Current Selection

`src/harness/graph.py` binds all Personal OS tools and all MCP gateway tools to the primary LLM in `node_agent()`:

- `get_registered_tools()` loads Personal OS and MCP tools.
- `node_agent()` calls `resolve_primary_llm()` and then `llm.bind_tools(tools)`.
- Tool calls are executed synchronously in `node_tools()`.

### Relation to Memory Retrieval

Tool routing is in the same graph as retrieval and memory management but not directly mixed with retrieval planning. The completed memory architecture keeps secondary LLM work in worker handlers; tool routing is still primary-chat-path behavior.

### Primary vs Secondary LLM

Primary LLM:

- Can call user-facing tools through `bind_tools`.
- Executes tool selection in chat path.

Secondary LLM:

- Memory worker handlers do not bind the tool registry.
- No direct evidence that secondary LLM can call user-facing tools in current memory handlers.

Gap:

- There is no formal role boundary in the tool registry itself. Future handlers could import `get_all_mcp_tools()` accidentally unless architecture forbids it and tests enforce it.

### Execution Model

- Tool execution is synchronous in `node_tools()`.
- High-risk tool approval pauses graph execution.
- After approval, `resume_graph_after_approval()` invokes the target tool synchronously.
- Tool call/result audit is persisted in `loop_events`, `tool_calls`, `tool_results`, and `audit_logs`.

Gaps:

- No queued/durable execution for tool calls.
- No retry/dead-letter behavior for tools.
- Risk classification is split between `src/hitl/classifier.py` and `TOOL_RISK_MAP` in `src/mcp_gateway/registry.py`, and the two disagree.
- Low/medium/high does not cover external communication, destructive action, scheduled future action, or local OS scope.
- Tool results are persisted, but not consistently redacted or surfaced in a tool observability API.

## 8. Approval / Policy Analysis

### Current Risk Classification

High risk in `src/hitl/classifier.py`:

- `bank_transfer`
- `spend_money`
- `production_deploy`
- `delete_database`
- `send_email`
- `email_send`
- `whatsapp_send`
- `telegram_send`
- `delete_files`
- `github_merge`
- `calendar_create_event`
- `calendar_delete_event`

Medium risk:

- `github_commit_and_push`
- `schedule_job`
- `spawn_agent`

Low risk:

- Everything else by default.

### Policy Gaps

- `src/mcp_gateway/registry.py` has a separate `TOOL_RISK_MAP` that marks `calendar_update_event` and `calendar_delete_event` Low while `src/hitl/classifier.py` treats delete as High and omits update.
- `run_code` is Low despite executing local Python.
- `capture_screenshot` is Low despite writing files.
- `github_clone` is Low despite writing files.
- REST routes bypass graph HITL for some write actions:
  - `PUT /api/calendar/events/{event_id}` directly updates.
  - `POST /api/email/draft` directly writes.
  - `POST /api/scheduled` directly schedules.
  - `POST /api/github/commit_and_push` directly executes.
- Approval request finalization executes tools by name through the shared registry, which currently includes tools targeted for removal.

### Target Risk Classes

| Risk class | Examples | Execution policy |
|---|---|---|
| Read-only | Search, read calendar availability, read email metadata, heartbeat, list tasks | Direct if credentials and scope are valid |
| Low-risk write | Local draft creation, local task note, non-external state update | Direct or lightweight confirmation depending scope |
| High-risk write | Calendar create/update/delete, file/system modifications, task lifecycle changes with side effects | HITL required |
| External communication | Gmail send, WhatsApp send, Telegram send | HITL required, preview required |
| Destructive action | Deletes, irreversible state changes | HITL required, some actions blocked |
| Scheduled future action | Any future execution | Approval at schedule creation; high-risk actions require execution-time approval or durable preapproval |

### Required Boundaries

- MCP-specific policy should wrap provider-managed tools without reimplementing them.
- Personal OS policy should be local and memory-aware.
- Cron policy should evaluate both schedule creation and due execution.
- Removed sandbox tools should be blocked during migration before deletion.

## 9. Frontend Analysis

### Current UI

- `frontend/src/components/ToolsCockpit.jsx`
  - Shows Personal OS tools and MCP Gateway tools from `/api/tools`.
  - Displays `risk_level`, but Personal OS catalog does not currently include risk metadata.
- `frontend/src/components/ScheduledCockpit.jsx`
  - Lists scheduled jobs.
  - Creates and cancels jobs.
  - No timezone, recurrence, missed-run, approval, or execution status controls.
- `frontend/src/components/ApprovalInbox.jsx`
  - Lists pending approval requests.
  - Approves/rejects through `/api/approvals/{request_id}/decision`.
- `frontend/src/components/MemoryObservabilityCockpit.jsx`
  - Memory Ops only; no tools observability.
- `frontend/src/components/OverviewCockpit.jsx`
  - Static text says tool status is "Operational (22 OS + MCP Gateway)".

### Browser/Code Sandbox UI to Remove

There is no dedicated browser/code sandbox component found, but their presence leaks through:

- Tools catalog entries.
- Integration status API.
- Product/readiness tests.

### Missing UI for Target Architecture

- MCP provider status by provider:
  - Tavily/DuckDuckGo Search MCP
  - Google Calendar MCP
  - WhatsApp MCP
  - Telegram MCP
  - Gmail MCP
- Tool invocation/audit timeline.
- Approval policy matrix.
- Personal OS operations panel.
- Cron schedule panel with next run, timezone, recurrence, missed runs, and approval state.
- Removed-tool deprecation/absence state.

## 10. Test Analysis

### Tests to Preserve

- MCP protocol basics:
  - `tests/test_mcp_protocol_adapters.py`, after replacing simulated SSE assumptions if needed.
- HITL core:
  - `tests/test_hitl.py`
  - `tests/test_p3_strengthen_hitl.py`, after removing GitHub sandbox expectations.
  - `tests/test_p6_security.py`, after removing `run_code` expectations.
- Personal OS behavior:
  - `tests/test_personal_os.py`, but should be rewritten around redesigned Personal OS semantics.
- Scheduling:
  - `tests/test_taskboard_and_scheduling.py`, but current assertions should be updated for real cron behavior.
- API/frontend smoke:
  - Existing API/frontend tests should be preserved but updated for removed endpoints and new MCP status.

### Tests to Delete With Browser/Code Sandbox

Delete after replacement coverage exists:

- `tests/test_p4_browser.py`
- Browser sections of `tests/test_mcp_gateway.py`
- Browser section of `tests/test_real_tools.py`
- Browser assertions in `tests/test_p7_product_readiness.py`
- Browser truthfulness assertions in `tests/test_p1_integration_truthfulness.py`
- `run_code` sandbox portions of `tests/test_mcp_gateway.py`
- `tests/test_p4_github.py`
- `run_code` import/assertions in `tests/test_e2e.py`
- `test_run_code_dev_only_and_boundaries` in `tests/test_p6_security.py`

### Tests to Migrate

- `tests/test_p4_search.py`: local adapter tests -> MCP search discovery/routing tests.
- `tests/test_p4_calendar.py`: SQLite calendar CRUD tests -> Google Calendar MCP wiring/policy tests.
- `tests/test_p4_email.py`: SMTP/IMAP tests -> Gmail MCP wiring/policy tests.
- `tests/test_p5_real_provider_integrations.py`: direct REST/SMTP tests -> provider-managed MCP integration tests.
- `tests/test_mcp_gateway.py`: local tool catalog -> provider discovery and local registry policy tests.
- `tests/test_real_tools.py`: local "real tools" -> MCP boundary/approval tests.

### Missing Tests

- MCP provider discovery for each target provider.
- Missing credential behavior for each MCP provider.
- Duplicate local implementation prevention.
- Agent routing to MCP tools through primary LLM only.
- Secondary memory worker cannot call user tools.
- HITL policy by risk class.
- Approval idempotency for MCP tool execution.
- Cron recurrence, timezone, missed-run, one-time scheduling.
- Tool observability and redaction.
- Frontend MCP provider status and cron panels.

## 11. Gap Table

| Area | Current State | Target State | Gap | Risk | Recommended Action | Files Involved | Phase Recommendation |
|---|---|---|---|---|---|---|---|
| Tool registry | Personal OS plus static local MCP tools plus optional live MCP tools | Clear local non-MCP registry plus provider-managed MCP registry | Static local adapters masquerade as MCP | High | Split registries and metadata | `src/personal_os/registry.py`, `src/mcp_gateway/registry.py`, `src/harness/graph.py` | Phase 1 |
| Browser sandbox | Registered, routed, API-exposed, tested | Removed completely | Live imports/routes/tests | High | Remove after blocking and cleanup | `browser_sandbox.py`, `server.py`, tests, deps | Phase 1 |
| Code sandbox | Registered, routed, API-exposed, tested | Removed completely | Live imports/routes/tests | High | Remove after blocking and cleanup | `code_sandbox.py`, `server.py`, tests, HITL docs | Phase 1 |
| Personal OS | 22 direct LangChain tools | Main local non-MCP layer built on memory architecture | No memory-aware model, weak policy | High | Redesign repositories, policy, audit, observability | `src/personal_os/*`, `src/orchestration/*`, `src/hitl/*` | Phase 2 |
| Cron | Durable rows, polling worker, no real cron | Reliable scheduler tool | No recurrence/timezone/missed-run/action dispatch | High | Redesign scheduler table and execution boundary | `scheduling.py`, `background_worker.py`, `server.py`, `ScheduledCockpit.jsx` | Phase 3 |
| Search MCP | Local Tavily REST/DDG adapter | Tavily or DuckDuckGo MCP | Provider behavior reimplemented locally | Medium | Replace with MCP discovery/invocation wrapper | `search.py`, `search_adapters.py`, `mcp_bridge.py` | Phase 4 |
| Google Calendar MCP | Local SQLite plus optional REST | Google Calendar MCP | Local source of truth and policy mismatch | High | Replace CRUD implementation with MCP boundary | `calendar.py`, `google_calendar_sync.py`, API/calendar tests | Phase 4 |
| WhatsApp MCP | Local SQLite plus optional REST | WhatsApp MCP | Local provider implementation | High | Replace with MCP boundary | `communication.py`, tests, env docs | Phase 4 |
| Telegram MCP | Local SQLite plus optional REST | Telegram MCP | Local provider implementation | High | Replace with MCP boundary | `communication.py`, tests, env docs | Phase 4 |
| Gmail MCP | SMTP/IMAP adapter | Gmail MCP | Wrong provider model | High | Replace with Gmail MCP boundary | `communication.py`, `email_adapters.py`, tests, env docs | Phase 4 |
| Tool routing | Primary LLM binds all tools | Primary-only user-facing tools, secondary blocked | No registry-level role enforcement | Medium | Add role-aware tool router/policy | `graph.py`, tool registries, tests | Phase 5 |
| Approval policy | Name-only classifier plus separate MCP risk map | Central policy with risk classes | Inconsistent and incomplete | High | Consolidate policy and require HITL where needed | `hitl/classifier.py`, `mcp_gateway/registry.py`, API routes | Phase 5 |
| Tool audit | loop/tool/audit tables exist | Redacted observability and execution history | Incomplete redaction/status UI | Medium | Add read-only tools observability | `tool_calls`, `tool_results`, `audit_logs`, frontend | Phase 6 |
| Frontend | Catalog, approvals, simple schedules | MCP status, Personal OS, cron observability | Missing target operations panels | Medium | Add observability-only UI after backend | `frontend/src/components/*` | Phase 6 |
| Docs/config | Old architecture advertises local adapters/sandboxes | Target tools architecture docs | Stale env/dependency docs | Medium | Update docs and env templates | `docs/ARCHITECTURE.md`, `.env.example`, README | Phase 7 |

## 12. Deletion Candidate Lists

### Files Safe to Delete Immediately

No tracked runtime source file is safe to delete immediately. Browser and code sandbox modules have live imports from `src/mcp_gateway/registry.py` and `src/api/server.py`.

Generated caches such as `__pycache__` are safe to ignore and may be removed by normal cleanup tooling, but they are not part of the tracked migration decision.

### Files to Delete After Reference Cleanup

- `src/mcp_gateway/sandboxes/browser_sandbox.py`
- `src/mcp_gateway/sandboxes/code_sandbox.py`
- `src/mcp_gateway/sandboxes/__init__.py` if the package becomes empty

### Tests to Delete After Replacement Coverage Exists

- `tests/test_p4_browser.py`
- `tests/test_p4_github.py`
- Browser/code portions of `tests/test_mcp_gateway.py`
- Browser/code portions of `tests/test_real_tools.py`
- `run_code` portions of `tests/test_e2e.py`
- Browser/GitHub sandbox assertions in `tests/test_p7_product_readiness.py`
- Browser/GitHub truthfulness assertions in `tests/test_p1_integration_truthfulness.py`
- Code sandbox boundary test in `tests/test_p6_security.py`

### Frontend Files or Components Safe to Delete

No dedicated frontend browser/code sandbox component was found. Do not delete full frontend components yet.

Reference cleanup required in:

- `frontend/src/components/ToolsCockpit.jsx`, because catalog entries will disappear/change.
- `frontend/src/components/OverviewCockpit.jsx`, because static tool status text is stale.
- `frontend/src/components/ScheduledCockpit.jsx`, because cron semantics need redesign.

### Docs, Config, Dependencies to Remove or Update

Remove after sandbox deletion:

- `playwright>=1.40.0` from `requirements.txt` if no frontend/e2e test still needs Python Playwright.
- `playwright>=1.40.0` from `pyproject.toml` under the same condition.
- Browser sandbox setup text in `docs/ARCHITECTURE.md`.

Update:

- `.env.example`:
  - remove SMTP/IMAP as Gmail MCP configuration if no longer needed.
  - add MCP-provider credential/config guidance.
  - add missing `WHATSAPP_PHONE_NUMBER_ID` if WhatsApp MCP still requires it.
  - add Google Calendar MCP credential guidance.
- `.agent/mcp_config.json`:
  - replace demo `filesystem` and `fetch_sse` entries with target provider MCP servers or document them as local development examples only.
- `README.md` and `docs/ARCHITECTURE.md`:
  - remove browser/code sandbox claims.
  - clarify provider-managed MCP boundaries.

### Files That Must Be Preserved

- Completed memory architecture under `src/memory/*`.
- HITL approval foundation under `src/hitl/*`, with policy refactor.
- MCP protocol foundation:
  - `src/mcp_gateway/protocol/*`
  - `src/mcp_gateway/mcp_bridge.py`, after refactor/hardening.
- Tool audit tables and support:
  - `tool_calls`
  - `tool_results`
  - `audit_logs`
  - `loop_events`
- Frontend approval inbox, after policy updates.
- Memory Ops frontend, unchanged except cross-links if desired.

### Files That Require Migration

- `src/mcp_gateway/registry.py`
- `src/mcp_gateway/search.py`
- `src/mcp_gateway/search_adapters.py`
- `src/mcp_gateway/calendar.py`
- `src/mcp_gateway/google_calendar_sync.py`
- `src/mcp_gateway/communication.py`
- `src/mcp_gateway/email_adapters.py`
- `src/personal_os/registry.py`
- `src/personal_os/tasks.py`
- `src/personal_os/scheduling.py`
- `src/personal_os/agent_lifecycle.py`
- `src/personal_os/concurrency.py`
- `src/personal_os/event_bus.py`
- `src/personal_os/context.py`
- `src/personal_os/checkpointing.py`
- `src/personal_os/execution_control.py`
- `src/harness/graph.py`
- `src/api/server.py`
- `src/hitl/classifier.py`
- `src/hitl/approval_engine.py`
- `frontend/src/components/ToolsCockpit.jsx`
- `frontend/src/components/ScheduledCockpit.jsx`
- `frontend/src/components/OverviewCockpit.jsx`

### Unknowns Requiring Manual Validation

- Which MCP providers are actually installed and available outside the local `.agent/mcp_config.json`.
- Whether Tavily, DuckDuckGo, Google Calendar, WhatsApp, Telegram, and Gmail MCP servers are expected to be app-installed connectors, stdio servers, or remote SSE/HTTP servers.
- Exact credential model for each MCP provider.
- Whether existing local SQLite communication/calendar tables should remain as caches/audit tables or be removed after MCP migration.
- Whether GitHub sandbox endpoints should be removed without replacement or replaced later by a separate GitHub connector migration outside this target.
- Whether Python Playwright is still required for frontend smoke tests after browser sandbox removal.
- Whether the scheduler should execute only Personal OS actions or also MCP actions after approval.

## Recommended Migration Direction

### Phase 1: Tool Registry Separation and Sandbox Removal Prep

- Split Personal OS and MCP provider registries.
- Remove browser/code sandbox tools from active agent binding behind a compatibility guard.
- Add failing tests proving sandbox tools are not exposed.
- Then delete sandbox routes/tests/dependencies in a separate mergeable step.

### Phase 2: Personal OS Redesign Foundation

- Introduce a memory-aware Personal OS tool boundary.
- Add typed tool metadata, risk policy, approval requirements, audit redaction, and observability.
- Preserve task/checkpoint concepts but replace synthetic context/sleep/event stubs.

### Phase 3: Cron-job Fix

- Redesign scheduler persistence and cron parsing.
- Add timezone, next_run_at, last_run_at, recurrence, missed-run policy, execution attempts, and approval state.
- Keep schedule definitions separate from `memory_jobs`.

### Phase 4: MCP Provider Wiring

- Configure and verify provider-managed MCP tools:
  - Tavily/DuckDuckGo Search MCP
  - Google Calendar MCP
  - WhatsApp MCP
  - Telegram MCP
  - Gmail MCP
- Remove local provider reimplementations except thin wrappers around discovery/routing/invocation.

### Phase 5: Tool Routing and Approval Policy

- Enforce primary-only user-facing tool calls.
- Ensure secondary memory workers cannot call user-facing tools.
- Consolidate risk classification across API, registry, graph, and MCP wrappers.
- Require HITL for high-risk writes, external communication, destructive actions, and scheduled future actions.

### Phase 6: Tools Observability and Frontend

- Add tools operations view for registry status, MCP health, Personal OS state, cron schedules, approvals, tool calls/results, and audit logs.
- Redact prompts, credentials, message bodies, and provider payloads by default.

### Phase 7: Docs, Tests, and Cleanup

- Rewrite tests around provider-managed MCP boundaries.
- Remove obsolete sandbox/local-adapter tests.
- Update docs, env templates, and dependency lists.

## Final Recommendation

Proceed next with a migration blueprint for the Tools architecture. The blueprint should dependency-order the work as:

1. Isolate and cleanly classify all tools.
2. Remove browser/code sandbox exposure and then delete sandbox code.
3. Redesign Personal OS as the durable local non-MCP tool layer.
4. Fix cron scheduling as its own durable scheduler subsystem.
5. Replace local provider implementations with provider-managed MCP discovery, routing, policy, invocation, observability, and error handling.
6. Harden frontend, tests, docs, and operator guidance.

