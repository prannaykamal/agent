# Tools Architecture Migration Roadmap

Generated from:

- `docs/tools-gap-analysis.md`
- `docs/tools-migration-blueprint.md`
- current codebase
- completed memory architecture
- existing HITL approval system
- existing observability system
- existing frontend tool, approval, scheduled-job, and Memory Ops panels

This roadmap is implementation planning only. It does not implement code, delete files, or modify runtime behavior.

## 1. Executive Summary

The Tools migration converts the current mixed local-adapter/tool-sandbox architecture into a bounded, secure, observable tools system.

The final architecture has two local non-MCP tool areas:

- Personal OS tools: local assistant operations, task state, approved local workflows, checkpoints, and bounded operator actions.
- cron-job tool: durable local scheduling for assistant actions.

The final architecture has five provider-managed MCP tool families:

- Tavily or DuckDuckGo Search MCP.
- Google Calendar MCP.
- WhatsApp MCP.
- Telegram MCP.
- Gmail MCP.

The migration removes completely:

- browser sandbox.
- code sandbox.

The central correction is architectural: MCP tools are provider-managed. The local system must wire, route, secure, observe, and test MCP tools, not reimplement provider behavior. The current local adapters under `src/mcp_gateway/` should either become thin MCP routing boundaries, be removed, or be preserved only as explicitly documented audit/cache compatibility surfaces.

The roadmap is dependency-ordered. It begins with tests and metadata, then removes sandbox exposure before deleting files, then redesigns Personal OS and cron, then wires MCP providers, then centralizes routing and HITL policy, then updates observability, frontend, docs, and E2E coverage.

## 2. Non-Goals

- No local reimplementation of MCP provider tools.
- No browser sandbox in the final architecture.
- No code sandbox in the final architecture.
- No unsafe tool execution without policy evaluation and approval where required.
- No worker auto-start unless explicitly designed in a later approved implementation.
- No memory architecture rewrite.
- No secondary LLM access to user-facing tools.
- No MCP provider behavior duplicated locally.
- No direct Tavily, DuckDuckGo, Google Calendar, WhatsApp, Telegram, or Gmail provider calls from local adapter functions in the final architecture.
- No automatic legacy provider-data backfill unless a later migration explicitly designs it.
- No broad Personal OS catch-all tool bucket.

## 3. Final Target Architecture

### Personal OS Local Tool Layer

Personal OS is the bounded local operations layer. It owns local assistant state and operator workflows that do not belong to external providers. It may use semantic, episodic, procedural, summary, and retrieval systems only through approved memory boundaries.

Personal OS must not send Gmail, WhatsApp, Telegram, Calendar, or search provider requests directly.

### Cron-job Local Scheduler Tool

cron-job owns durable schedule definitions and schedule run attempts. It supports one-time and recurring schedules, timezones, missed-run policy, retries, cancellation, update, policy checks, approval integration, and observability.

Cron is not Google Calendar. Google Calendar MCP is for calendar events; cron-job is for scheduled assistant actions.

### Provider-managed MCP Tool Layer

Provider MCP servers/connectors own provider behavior. Local code owns:

- provider discovery.
- MCP registration.
- metadata normalization.
- routing.
- permission/HITL policy.
- invocation boundary.
- error handling.
- observability.
- frontend status.

### Unified Tool Registry

The registry must distinguish:

- `implementation_type = local`
- `implementation_type = mcp`
- `implementation_type = removed`

Registry metadata includes tool identity, provider, category, enabled status, availability, risk class, approval policy, read/write capability, side-effect flags, destructive flag, scheduled-capable flag, provider-managed flag, schemas, and observability metadata.

### Tool Routing

Only the primary user-facing agent can bind user-facing tools. The secondary memory LLM and memory worker handlers must not bind or invoke Personal OS, cron, or MCP user-facing tools.

### HITL Policy

A single consolidated policy evaluates tools across graph, API, scheduler, MCP invocation, and approval resume. High-risk writes, external communication, destructive actions, and scheduled future actions require HITL or are blocked.

### Tool Invocation Audit

All tool invocations should write redacted tool call/result/audit records. Existing `tool_calls`, `tool_results`, `audit_logs`, and `loop_events` can be preserved and extended.

### Tools Observability

Tools observability mirrors memory observability:

- read-only by default.
- redacted.
- status and diagnostics without secrets or raw provider payloads.
- includes registry health, MCP provider status, tool calls, approvals, cron schedules/runs, Personal OS actions, failures, and blocked removed-tool attempts.

### Frontend Panels

The existing `ToolsCockpit`, `ScheduledCockpit`, `ApprovalInbox`, `OverviewCockpit`, and Memory Ops panels should evolve into:

- unified tools catalog.
- MCP provider status panels.
- Personal OS status/actions/audit panel.
- cron schedule/run panel.
- tool audit panel.
- approval inbox compatibility.
- removed-tool visibility only in operator tools ops views.

### Relationship With Completed Memory Architecture

Memory remains the background learning and retrieval system. Tools may create memory-relevant events through approved boundaries, but tools do not rewrite memory architecture and do not overload `memory_jobs` for general tool execution or schedule definitions.

## 4. Phase List

### Phase T0: Baseline Tools Audit and Test Snapshot

#### Goal

Freeze current behavior and add safety tests before any tool exposure changes.

#### Scope

- Capture current tool registry output.
- Add tests documenting browser/code sandbox exposure.
- Add static scan tests for known sandbox references.
- Add tests proving secondary memory workers do not bind user-facing tools.
- Document current MCP provider config unknowns.

#### Out of Scope

- Runtime behavior changes.
- Registry refactor.
- Sandbox deletion.
- MCP provider replacement.

#### Files Likely Changed

- `tests/test_tools_t0_baseline_registry.py`
- `tests/test_tools_t0_static_scans.py`
- `tests/test_tools_t0_secondary_llm_tool_boundary.py`
- `docs/tools-mcp-provider-validation.md` or a section in this roadmap's follow-up docs.

#### Files Likely Deleted

- None.

#### API Changes

- None.

#### Frontend Changes

- None.

#### Tests to Add

- Current `/api/tools` includes Personal OS and current MCP gateway tools.
- Current registry exposes browser/code sandbox tools, explicitly marked as baseline to be removed later.
- Static scan finds current sandbox references.
- Memory worker modules do not call `get_all_personal_os_tools()`, `get_all_mcp_tools()`, or unified tool binding functions.
- Current `.agent/mcp_config.json` does not configure target providers.

#### Regression Tests to Run

```powershell
python -m pytest tests/test_api_server.py tests/test_harness.py tests/test_mcp_gateway.py tests/test_personal_os.py tests/test_taskboard_and_scheduling.py -q
```

#### Static Scans to Run

```powershell
rg -n "browser_sandbox|code_sandbox|safe_browse_url|capture_screenshot|run_code|github_clone|github_commit_and_push|github_merge|/api/browser|/api/github" src frontend tests docs README.md pyproject.toml requirements.txt
rg -n "resolve_secondary_llm|get_secondary_llm|\.invoke\(" src/memory src/harness src/mcp_gateway src/personal_os
```

#### Acceptance Criteria

- Baseline tests pass.
- Known current sandbox exposure is documented.
- No secondary memory worker user-tool binding is observed.
- MCP provider config unknowns are explicitly documented.

#### Rollback Strategy

- Revert only added baseline tests/docs.

#### Risks

- Baseline tests may lock in undesirable behavior. Name them clearly as migration-baseline tests.

#### Manual Validation Needed

- Confirm expected MCP provider delivery model: installed app connector, stdio MCP, SSE/HTTP MCP, or local config.

#### Codex Implementation Prompt Outline

Implement Phase T0 baseline tests and provider-config documentation only. Do not change runtime behavior, registries, routes, frontend, or tool implementations.

### Phase T1: Tool Registry Separation and Removed-Tool Metadata

#### Goal

Introduce the unified registry model and separate local, MCP, and removed-tool metadata without changing active runtime behavior yet.

#### Scope

- Add registry dataclasses/types.
- Add local/MCP/removed implementation types.
- Represent browser/code sandbox tools as removed-target metadata while still preserving current app startup.
- Provide compatibility wrappers for existing catalog shape.

#### Out of Scope

- Removing active sandbox exposure.
- Deleting sandbox files.
- MCP provider replacement.
- Personal OS behavior redesign.

#### Files Likely Changed

- New `src/tools/registry_types.py`
- New `src/tools/registry.py`
- New `src/tools/removed_tools.py`
- `src/personal_os/registry.py`
- `src/mcp_gateway/registry.py`
- `src/api/server.py` only if needed for catalog compatibility.
- Tests.

#### Files Likely Deleted

- None.

#### API Changes

- Keep `/api/tools` response shape compatible.
- Optionally add internal metadata fields behind additive keys if safe.

#### Frontend Changes

- None or minimal compatibility adjustments if additive keys are introduced.

#### Tests to Add

- Registry entries include `implementation_type`.
- Removed-target metadata exists for browser/code tools.
- Removed metadata is not the same as deletion.
- Existing `/api/tools` compatibility shape is preserved.
- Every tool has stable `tool_id`, risk class, provider, category, and availability.

#### Regression Tests to Run

```powershell
python -m pytest tests/test_api_server.py tests/test_frontend_api.py tests/test_mcp_gateway.py tests/test_personal_os.py -q
```

#### Static Scans to Run

```powershell
rg -n "ALL_MCP_TOOLS|ALL_PERSONAL_OS_TOOLS|TOOL_RISK_MAP|get_mcp_tool_risk|get_os_tool_catalog|get_mcp_tool_catalog" src
```

#### Acceptance Criteria

- Unified metadata exists.
- Current app startup remains intact.
- Active tool behavior remains unchanged.
- Removed-tool targets are represented but not yet blocked.

#### Rollback Strategy

- Revert new registry files and wrapper changes.

#### Risks

- Introducing duplicate registry paths may cause drift. Keep compatibility wrappers thin and tested.

#### Manual Validation Needed

- Decide final naming convention for provider-managed MCP `tool_id`s.

#### Codex Implementation Prompt Outline

Implement registry metadata types and compatibility wrappers only. Preserve active runtime behavior and `/api/tools` compatibility.

### Phase T2: Sandbox Exposure Removal and Blocking

#### Goal

Stop exposing browser/code sandbox tools to primary agent binding and active tool catalog, while keeping old files until references are cleaned.

#### Scope

- Remove browser/code tools from agent-bindable registry.
- Remove browser/code from active `/api/tools` catalog.
- Keep removed/blocked status in observability/catalog if needed.
- Block removed tools in graph tool execution.
- Block removed tools in approval resume.
- Keep old files on disk.

#### Out of Scope

- Deleting source files.
- Removing routes.
- Removing dependencies.
- MCP replacement.

#### Files Likely Changed

- `src/tools/registry.py`
- `src/tools/removed_tools.py`
- `src/harness/graph.py`
- `src/api/server.py`
- `src/hitl/classifier.py`
- `src/hitl/approval_engine.py`
- tests.

#### Files Likely Deleted

- None.

#### API Changes

- `/api/tools` no longer lists browser/code sandbox as active.
- Optional removed/blocked metadata may appear in additive fields.
- Browser/GitHub routes remain temporarily if needed but should return blocked/deprecated or be marked for T3.

#### Frontend Changes

- `ToolsCockpit.jsx` may need to tolerate active/removed grouping if `/api/tools` shape changes additively.

#### Tests to Add

- Browser/code tools are not bindable by primary agent.
- `/api/tools` active catalog excludes browser/code tools.
- Direct graph execution of removed tool returns blocked result.
- Approval resume cannot execute removed tools.
- Audit records blocked attempts.

#### Regression Tests to Run

```powershell
python -m pytest tests/test_harness.py tests/test_hitl.py tests/test_api_server.py tests/test_frontend_api.py -q
```

#### Static Scans to Run

```powershell
rg -n "safe_browse_url|capture_screenshot|run_code|github_clone|github_commit_and_push|github_merge" src/harness src/api src/hitl src/tools
```

#### Acceptance Criteria

- Removed tools are blocked and not agent-bindable.
- App startup still works.
- Old source files remain untouched until T3.
- No high-risk approval can resume a removed tool.

#### Rollback Strategy

- Re-enable prior registry exposure by reverting T2 changes.

#### Risks

- Existing tests expecting sandbox availability will fail and must be migrated in T3.

#### Manual Validation Needed

- Decide whether old browser/GitHub API routes should return HTTP 410 during transition or be removed directly in T3.

#### Codex Implementation Prompt Outline

Remove sandbox tools from active binding/catalog and add removed-tool blocking. Do not delete files or remove routes/dependencies yet.

### Phase T3: Sandbox Deletion and Dependency Cleanup

#### Goal

Delete browser/code sandbox implementations after all references are cleaned.

#### Scope

- Remove imports from registry/API/tests.
- Remove browser and GitHub/code API routes.
- Remove integration status entries.
- Remove/deprecate sandbox tests.
- Remove docs/config/dependency references.
- Delete sandbox source files.
- Prove no references remain.

#### Out of Scope

- MCP provider replacement.
- Personal OS redesign.
- Cron redesign.

#### Files Likely Changed

- `src/mcp_gateway/registry.py`
- `src/api/server.py`
- `src/hitl/classifier.py`
- `src/hitl/approval_engine.py`
- `README.md`
- `docs/ARCHITECTURE.md`
- `.env.example`
- `requirements.txt`
- `pyproject.toml`
- tests.

#### Files Likely Deleted

- `src/mcp_gateway/sandboxes/browser_sandbox.py`
- `src/mcp_gateway/sandboxes/code_sandbox.py`
- `src/mcp_gateway/sandboxes/__init__.py` if empty.
- `tests/test_p4_browser.py`
- `tests/test_p4_github.py`
- sandbox-only test sections after replacement coverage exists.

#### API Changes

- Remove:
  - `POST /api/browser/browse`
  - `POST /api/browser/screenshot`
  - `POST /api/github/clone`
  - `POST /api/github/commit_and_push`
  - `POST /api/github/merge`
- Remove browser/GitHub sandbox entries from `/api/integrations/status`.

#### Frontend Changes

- Update `ToolsCockpit.jsx` and `OverviewCockpit.jsx` to avoid showing sandbox tools/status.
- Ensure no frontend call expects `/api/browser/*` or `/api/github/*`.

#### Tests to Add

- Static scan proves no sandbox references remain.
- Removed endpoints are absent or documented as removed.
- `/api/tools` has no browser/code tools.
- `src.mcp_gateway.sandboxes` imports fail or are absent as expected.

#### Regression Tests to Run

```powershell
python -m pytest tests/test_api_server.py tests/test_frontend_api.py tests/test_p2_frontend_smoke.py tests/test_p3_frontend.py tests/test_harness.py -q
```

#### Static Scans to Run

```powershell
rg -n "browser sandbox|browser_sandbox|sandbox_browser|safe_browse_url|capture_screenshot|playwright|selenium|code sandbox|code_sandbox|python sandbox|run_code|exec_code|github_clone|github_commit_and_push|github_merge|/api/browser|/api/github" src frontend tests docs README.md pyproject.toml requirements.txt
```

#### Acceptance Criteria

- No tracked runtime sandbox file remains.
- No references to removed sandbox tools remain.
- App imports and API startup work.
- Tests no longer expect sandbox behavior.
- Dependencies/docs no longer advertise backend sandbox behavior.

#### Rollback Strategy

- Revert T3 commit to restore deleted files/routes if import failures are found.

#### Risks

- Removing Playwright may affect frontend E2E smoke tests if they use Python Playwright. Confirm dependency ownership before removal.

#### Manual Validation Needed

- Confirm GitHub sandbox removal does not conflict with any separate desired GitHub connector migration.

#### Codex Implementation Prompt Outline

Clean all browser/code sandbox references, remove routes/tests/docs/dependencies, delete sandbox files, and prove removal with static scans.

### Phase T4: Personal OS Redesign Foundation

#### Goal

Redesign Personal OS as a bounded, memory-aware local operations layer.

#### Scope

- Define target Personal OS tool namespaces.
- Add metadata, policy, idempotency, audit, and observability boundaries.
- Remove/replace synthetic tools unless justified.
- Integrate memory through approved retrieval/repository boundaries.
- Preserve compatible task/checkpoint APIs where possible.

#### Out of Scope

- Provider behavior.
- Cron recurrence implementation.
- MCP tool invocation replacement.
- Browser/code behavior.

#### Files Likely Changed

- `src/personal_os/registry.py`
- `src/personal_os/tasks.py`
- `src/personal_os/agent_lifecycle.py`
- `src/personal_os/concurrency.py`
- `src/personal_os/event_bus.py`
- `src/personal_os/context.py`
- `src/personal_os/checkpointing.py`
- `src/personal_os/execution_control.py`
- `src/api/server.py`
- new `src/tools/personal_os_*` modules if preferred.
- frontend Personal OS panel/tests.

#### Files Likely Deleted

- None initially. Synthetic tool modules may be removed only after references/tests are migrated.

#### API Changes

- Add:
  - `GET /api/tools/personal-os/status`
  - `GET /api/tools/personal-os/actions`
  - `GET /api/tools/personal-os/audit`
- Preserve `GET /api/tasks` compatibility.

#### Frontend Changes

- Add or extend Personal OS section in Tools Ops.
- Show bounded local tools, policy, status, and recent audit.

#### Tests to Add

- Personal OS read actions need no approval.
- Local writes go through policy.
- Synthetic tools absent or blocked.
- Personal OS does not call Gmail/WhatsApp/Telegram/Calendar/search provider logic.
- Personal OS uses memory retrieval/repositories only through approved boundaries.
- Idempotent write behavior.
- Audit records written/redacted.

#### Regression Tests to Run

```powershell
python -m pytest tests/test_personal_os.py tests/test_taskboard_and_scheduling.py tests/test_hitl.py tests/test_api_server.py tests/test_phase9b_graph_retrieval_integration.py -q
```

#### Static Scans to Run

```powershell
rg -n "smtp|imap|TAVILY|WHATSAPP|TELEGRAM|GOOGLE_CALENDAR|duckduckgo|DDGS|smtplib|imaplib|requests\\." src/personal_os
rg -n "sleep|wake|subscribe_event|acquire_context|release_context" src tests frontend docs
```

#### Acceptance Criteria

- Personal OS has explicit bounded responsibilities.
- Personal OS cannot directly send provider requests.
- Synthetic tools are removed, replaced, or blocked with documented rationale.
- Personal OS is observable and approval-aware.

#### Rollback Strategy

- Preserve compatibility wrappers until new Personal OS tests pass.
- Revert namespace/registry changes if graph binding breaks.

#### Risks

- Personal OS can become too broad. Enforce non-responsibilities in tests and docs.

#### Manual Validation Needed

- Confirm which existing Personal OS tools users still need as local operations.

#### Codex Implementation Prompt Outline

Implement bounded Personal OS metadata, policy, audit, observability, and memory-safe boundaries. Remove or block synthetic tools only with tests. Do not implement provider behavior.

### Phase T5: Cron-job Scheduler Fix

#### Goal

Replace the incomplete scheduled job poller with a durable scheduler subsystem.

#### Scope

- Add schedule definition/run model.
- Implement one-time schedules.
- Implement recurring cron expressions.
- Add timezone handling.
- Track `next_run_at` and `last_run_at`.
- Add missed-run policy.
- Add retries/cancel/update.
- Integrate approval for scheduled actions.
- Add observability and frontend updates.

#### Out of Scope

- Google Calendar replacement.
- MCP provider implementation.
- Memory job overload.
- Worker auto-start by default.

#### Files Likely Changed

- `src/personal_os/scheduling.py`
- `src/background_worker.py` or new explicit scheduler worker module.
- `src/db.py`
- `src/db_migrations.py`
- `src/api/server.py`
- `frontend/src/components/ScheduledCockpit.jsx`
- tests.

#### Files Likely Deleted

- None initially. Legacy `scheduled_jobs` stays until compatibility decision.

#### API Changes

- Add:
  - `GET /api/tools/cron/schedules`
  - `POST /api/tools/cron/schedules`
  - `GET /api/tools/cron/schedules/{schedule_id}`
  - `PATCH /api/tools/cron/schedules/{schedule_id}`
  - `DELETE /api/tools/cron/schedules/{schedule_id}`
  - `GET /api/tools/cron/runs`
- Keep `/api/scheduled` as compatibility wrapper during migration if feasible.

#### Frontend Changes

- Redesign `ScheduledCockpit.jsx`.
- Show one-time/recurring type, timezone, next run, last run, missed-run policy, run attempts, approval state, and failure state.

#### Tests to Add

- Empty DB migration creates scheduler tables.
- Existing DB migration preserves `scheduled_jobs`.
- One-time job executes once.
- Recurring cron computes next run.
- Timezone conversion works.
- Missed-run policies work.
- Cancel/update work.
- Retryable and terminal failures are recorded.
- High-risk scheduled action creates approval.
- Scheduler does not use `memory_jobs` as schedule definition table.

#### Regression Tests to Run

```powershell
python -m pytest tests/test_taskboard_and_scheduling.py tests/test_api_server.py tests/test_hitl.py tests/test_phase3b_worker_step.py -q
```

#### Static Scans to Run

```powershell
rg -n "scheduled_jobs|cron_or_timestamp|process_due_scheduled_jobs|run_scheduled_worker_loop|memory_jobs" src tests
```

#### Acceptance Criteria

- Durable one-time and recurring scheduler works.
- Scheduler is separate from `memory_jobs`.
- No scheduler worker auto-start is introduced accidentally.
- High-risk due actions are approval-gated.

#### Rollback Strategy

- Keep legacy `scheduled_jobs` and old API wrapper until the new scheduler passes tests.

#### Risks

- Timezone and missed-run bugs can cause duplicate or missed actions.
- Approval timing for future actions must be explicit.

#### Manual Validation Needed

- Choose cron parser dependency and supported cron syntax.
- Confirm default timezone source.

#### Codex Implementation Prompt Outline

Implement durable cron scheduler tables, parser, timezone, run attempts, approval-aware execution boundary, API/frontend observability, and tests. Do not use `memory_jobs` as scheduler definition storage.

### Phase T6: MCP Provider Wiring Foundation

#### Goal

Add provider-managed MCP discovery and metadata wiring for target providers without replacing local adapters yet.

#### Scope

- Validate target MCP provider config model.
- Discover/register provider-managed MCP tools.
- Normalize MCP tool schemas and metadata.
- Add provider unavailable behavior.
- Add tests with mocked MCP providers.
- Prevent local duplicate implementation in new MCP path.

#### Out of Scope

- Removing old provider adapters.
- Full API replacement.
- Sending real provider writes.

#### Files Likely Changed

- `src/mcp_gateway/mcp_bridge.py`
- `src/mcp_gateway/protocol/*`
- `src/mcp_gateway/registry.py`
- new `src/tools/mcp_provider_registry.py`
- new `src/tools/mcp_invocation.py`
- `src/config.py`
- `.agent/mcp_config.json` example guidance in docs, not necessarily runtime file.
- tests.

#### Files Likely Deleted

- None.

#### API Changes

- Add:
  - `GET /api/tools/mcp/providers`
  - `GET /api/tools/mcp/providers/{provider_id}`
  - optional explicit discovery refresh endpoint if approved.

#### Frontend Changes

- Add provider status display or prepare API for T9.

#### Tests to Add

- Mock MCP provider discovery for each target provider.
- Missing config marks provider unavailable.
- Discovery failure does not break chat.
- Schema normalization.
- Provider-managed metadata flag.
- No local provider implementation is called by MCP discovery path.

#### Regression Tests to Run

```powershell
python -m pytest tests/test_mcp_protocol_adapters.py tests/test_api_server.py tests/test_harness.py -q
```

#### Static Scans to Run

```powershell
rg -n "mcp_config|load_live_mcp_tools|create_langchain_tool_from_mcp|tools/list|tools/call" src tests docs
rg -n "TAVILY_API_KEY|SMTP_|IMAP_|WHATSAPP_API_TOKEN|TELEGRAM_BOT_TOKEN|GOOGLE_CALENDAR_TOKEN|requests\\.post|requests\\.get|smtplib|imaplib|duckduckgo_search|DDGS" src/mcp_gateway src/api tests docs README.md .env.example
```

#### Acceptance Criteria

- Target provider entries can be represented and discovered through MCP.
- Provider unavailable states are safe.
- No local duplicate behavior is added.
- Existing local adapters still work only as legacy paths until T7.

#### Rollback Strategy

- Disable new MCP provider registry path and fall back to existing registry behavior.

#### Risks

- MCP provider transport and config remain unknown.
- Simulated tests may not match real providers.

#### Manual Validation Needed

- For each target provider, confirm installed server/connector, transport, credentials, tool names, and schemas.

#### Codex Implementation Prompt Outline

Implement MCP provider discovery/metadata foundation with mocked provider tests and unavailable-state handling. Do not remove old local adapters or implement provider behavior locally.

### Phase T7: MCP Adapter Replacement and Local Provider Implementation Removal

#### Goal

Replace current local provider implementations with provider-managed MCP routing.

#### Scope

- Replace local search adapters with MCP routing.
- Replace local Google Calendar CRUD/REST with MCP routing.
- Replace local Gmail SMTP/IMAP with MCP routing.
- Replace local WhatsApp REST/SQLite send/read implementation with MCP routing.
- Replace local Telegram REST/SQLite send/read implementation with MCP routing.
- Decide old table role: audit/cache only or removal in a later schema cleanup.
- Remove direct provider API credentials from local code where obsolete.

#### Out of Scope

- Browser/code sandbox.
- Personal OS behavior.
- Cron behavior beyond invoking MCP boundary.
- Local provider reimplementation.

#### Files Likely Changed

- `src/mcp_gateway/search.py`
- `src/mcp_gateway/search_adapters.py`
- `src/mcp_gateway/calendar.py`
- `src/mcp_gateway/google_calendar_sync.py`
- `src/mcp_gateway/communication.py`
- `src/mcp_gateway/email_adapters.py`
- `src/api/server.py`
- `src/config.py`
- `.env.example`
- tests.

#### Files Likely Deleted

- Possibly after replacement:
  - `src/mcp_gateway/search_adapters.py`
  - `src/mcp_gateway/google_calendar_sync.py`
  - `src/mcp_gateway/email_adapters.py`
- Defer deletion if compatibility wrappers need one phase.

#### API Changes

- Existing calendar/email/search endpoints either become thin MCP wrappers or are deprecated in favor of provider-aware tool APIs.
- Preserve response shapes where feasible.

#### Frontend Changes

- Provider status replaces local adapter status.
- Tools catalog labels provider-managed MCP tools.

#### Tests to Add

- Search wrapper invokes MCP search tool, not local Tavily/DDG.
- Calendar wrapper invokes MCP calendar tool, not local SQLite/REST.
- Gmail wrapper invokes MCP Gmail tool, not SMTP/IMAP.
- WhatsApp wrapper invokes MCP WhatsApp tool, not Meta REST/local send.
- Telegram wrapper invokes MCP Telegram tool, not Bot REST/local send.
- Provider unavailable returns safe response.
- Local duplicate implementation scans pass.

#### Regression Tests to Run

```powershell
python -m pytest tests/test_api_server.py tests/test_harness.py tests/test_mcp_protocol_adapters.py tests/test_hitl.py -q
```

#### Static Scans to Run

```powershell
rg -n "TAVILY_API_KEY|SMTP_|IMAP_|WHATSAPP_API_TOKEN|TELEGRAM_BOT_TOKEN|GOOGLE_CALENDAR_TOKEN|requests\\.post|requests\\.get|smtplib|imaplib|duckduckgo_search|DDGS" src/mcp_gateway src/api tests docs README.md .env.example
```

#### Acceptance Criteria

- Target provider behavior is reachable only through MCP invocation boundaries.
- Local duplicate provider implementations are removed or inactive compatibility wrappers.
- Provider unavailable behavior is safe and tested.

#### Rollback Strategy

- Keep adapter replacement behind feature flag until provider-managed tests pass.
- Revert provider-specific replacement one provider at a time if needed.

#### Risks

- Real provider MCP tools may have different schemas than expected.
- Existing API tests may require compatibility wrappers.

#### Manual Validation Needed

- Run provider-specific manual discovery and smoke calls in a safe test account/environment.

#### Codex Implementation Prompt Outline

Replace local target-provider adapters with MCP routing wrappers and remove direct provider API calls. Keep provider-managed rule enforced by tests and scans.

### Phase T8: Unified Tool Routing and HITL Policy

#### Goal

Centralize tool permission policy and route all tool calls through a safe invocation boundary.

#### Scope

- Consolidate split risk maps.
- Classify read/write/external/destructive/scheduled actions.
- Enforce primary-only user-facing tool binding.
- Prevent secondary LLM tool access.
- Route approval-required calls through HITL.
- Handle approval resume for MCP and cron safely.
- Permanently block removed tools.
- Normalize tool errors.

#### Out of Scope

- New provider implementations.
- New memory behavior.
- Worker auto-start.

#### Files Likely Changed

- `src/hitl/classifier.py`
- `src/hitl/approval_engine.py`
- `src/hitl/audit_logger.py`
- `src/harness/graph.py`
- `src/api/server.py`
- `src/tools/*`
- `src/mcp_gateway/registry.py`
- `src/personal_os/registry.py`
- tests.

#### Files Likely Deleted

- Old duplicate risk map in `src/mcp_gateway/registry.py` if replaced.

#### API Changes

- Approval responses preserve shape.
- Add policy metadata to tool status/catalog APIs.

#### Frontend Changes

- Approval Inbox shows richer policy/preview metadata if additive.

#### Tests to Add

- Unified policy classifications for all tool classes.
- Calendar create/update/delete require approval.
- Gmail send requires approval.
- WhatsApp/Telegram send require approval.
- Cron-triggered writes require approval.
- Removed tools blocked.
- Approval resume cannot execute removed/unavailable tools.
- Primary-only binding.
- Secondary LLM cannot bind/invoke user-facing tools.

#### Regression Tests to Run

```powershell
python -m pytest tests/test_hitl.py tests/test_harness.py tests/test_api_server.py tests/test_phase3b_router_handlers.py tests/test_phase5b_summary_job_handler.py tests/test_phase6b_episode_handler.py tests/test_phase7c_consolidation_handler.py -q
```

#### Static Scans to Run

```powershell
rg -n "TOOL_RISK_MAP|classify_tool_risk|create_approval_request|approval_required|policy_check|AskPermission|HITL" src/tools src/personal_os src/mcp_gateway src/harness src/api src/hitl
rg -n "resolve_secondary_llm|get_secondary_llm|\.bind_tools|get_all_mcp_tools|get_all_personal_os_tools" src/memory src/harness src/tools
```

#### Acceptance Criteria

- One policy model controls graph/API/scheduler/MCP invocation.
- Removed tools are blocked everywhere.
- Secondary memory LLM cannot access user-facing tools.
- Approval resume is safe and idempotent.

#### Rollback Strategy

- Preserve old classifier wrapper while new policy service is introduced.

#### Risks

- Tightening policy may break tests expecting direct writes. Update tests to target approved architecture.

#### Manual Validation Needed

- Confirm which actions are allowed as confirmation recommended versus approval required.

#### Codex Implementation Prompt Outline

Implement unified tool policy and routing boundary across graph/API/scheduler/MCP. Preserve API shapes and block removed tools. Do not add provider behavior.

### Phase T9: Tools Observability and Frontend Updates

#### Goal

Expose safe read-only tools observability and update frontend panels for the final tool architecture.

#### Scope

- Tools Ops observability APIs.
- Tool registry/status API.
- MCP provider status panels.
- Personal OS panel.
- Cron schedule/run panel.
- Tool call audit panel.
- Removed/blocked attempts visibility.
- Overview/Tools/Scheduled/Approval UI updates.

#### Out of Scope

- New write controls except explicit existing admin actions.
- Chat behavior changes.
- Memory observability changes.

#### Files Likely Changed

- `src/api/server.py`
- new `src/tools/observability.py`
- `frontend/src/components/ToolsCockpit.jsx`
- `frontend/src/components/ScheduledCockpit.jsx`
- `frontend/src/components/ApprovalInbox.jsx`
- `frontend/src/components/OverviewCockpit.jsx`
- new frontend Tools Ops component.
- frontend styles/tests.

#### Files Likely Deleted

- None, unless stale sandbox UI fragments remain.

#### API Changes

- Add:
  - `GET /api/tools/status`
  - `GET /api/tools/mcp/providers`
  - `GET /api/tools/personal-os/status`
  - `GET /api/tools/personal-os/actions`
  - `GET /api/tools/personal-os/audit`
  - `GET /api/tools/cron/schedules`
  - `GET /api/tools/cron/runs`
  - `GET /api/tools/observability/overview`
  - `GET /api/tools/observability/calls`
  - `GET /api/tools/observability/results`
  - `GET /api/tools/observability/audit`
  - `GET /api/tools/observability/blocked`

#### Frontend Changes

- Update Tools Catalog grouping.
- Redesign ScheduledCockpit.
- Keep ApprovalInbox compatible.
- Clean Overview text.
- Add Tools Ops panel.
- Show MCP provider unavailable states.
- Show removed tools only in ops/blocked view.

#### Tests to Add

- Observability endpoints are read-only.
- Provider status redacts secrets.
- Tool audit redacts payloads.
- Removed/blocked attempts visible.
- Frontend renders empty/error states.
- Frontend calls no unsafe write endpoints.

#### Regression Tests to Run

```powershell
python -m pytest tests/test_api_server.py tests/test_frontend_api.py tests/test_p2_frontend_smoke.py tests/test_p3_frontend.py tests/test_phase10_memory_observability_api.py -q
npm run build
```

#### Static Scans to Run

```powershell
rg -n "api_key|secret|token|authorization|password|credential|chain_of_thought|scratchpad|reasoning" src/api src/tools frontend/src
rg -n "fetch\\(\"/api/browser|fetch\\('/api/browser|fetch\\(\"/api/github|fetch\\('/api/github" frontend/src
```

#### Acceptance Criteria

- Tools observability is read-only and redacted.
- Frontend reflects final architecture.
- Removed tools are not shown as available.
- Memory Ops remains unaffected.

#### Rollback Strategy

- Hide new frontend panel while retaining backend APIs if UI errors occur.

#### Risks

- Observability can accidentally leak payloads. Redaction tests are mandatory.

#### Manual Validation Needed

- Validate frontend display with no providers configured and with mocked providers available.

#### Codex Implementation Prompt Outline

Add read-only tools observability APIs and frontend panels. Redact secrets and payloads. Do not change chat, memory, provider behavior, or add unsafe write controls.

### Phase T10: Tools Docs, E2E Hardening, and Final Cleanup

#### Goal

Complete documentation, operator guidance, full E2E coverage, static scans, and final cleanup.

#### Scope

- Tools architecture docs.
- Operator runbook.
- MCP wiring guide.
- Security policy.
- Cron docs.
- Personal OS docs.
- README and env guidance.
- Full backend and frontend regression.
- Final static scans.

#### Out of Scope

- New features.
- Provider behavior implementation.
- Memory rewrite.

#### Files Likely Changed

- `docs/tools-architecture.md`
- `docs/tools-operator-runbook.md`
- `docs/tools-mcp-wiring.md`
- `docs/tools-security-policy.md`
- `docs/tools-cron-jobs.md`
- `docs/tools-personal-os.md`
- `README.md`
- `.env.example`
- `.agent/mcp_config.example.json` or docs guidance.
- E2E tests.

#### Files Likely Deleted

- Any remaining obsolete sandbox docs/tests discovered by scans.

#### API Changes

- None beyond final documented cleanup.

#### Frontend Changes

- Final polish only.

#### Tests to Add

- End-to-end chat with provider unavailable.
- End-to-end read-only MCP search with mocked provider.
- End-to-end approval flow for external communication.
- End-to-end cron read action and cron approval-gated write action.
- End-to-end Personal OS read/write policy.
- Final no-sandbox references test.
- Final no-local-provider-duplicate test.

#### Regression Tests to Run

```powershell
python -m pytest -q
npm run build
```

#### Static Scans to Run

Run all commands in Section 18.

#### Acceptance Criteria

- Final acceptance criteria in Section 17 pass.
- Docs match implementation.
- Full suite passes.
- Frontend build passes.
- Static scans prove no sandbox or duplicate provider behavior remains.

#### Rollback Strategy

- Roll back final docs/tests if they overstate behavior. Runtime changes should already be stable from prior phases.

#### Risks

- Docs can drift from implementation. Use static scans and E2E tests as evidence.

#### Manual Validation Needed

- Provider MCP smoke tests in safe accounts.
- Operator review of approval/security policy.

#### Codex Implementation Prompt Outline

Add final docs, E2E tests, static scans, and cleanup only. Do not add new features. Confirm no sandbox/local duplicate provider behavior remains.

## 5. Deletion Roadmap

No tracked runtime sandbox file is safe to delete before reference cleanup.

### Browser Sandbox

#### Deletion Order

1. Add tests proving current exposure.
2. Add removed-tool metadata.
3. Remove from active registry and agent binding.
4. Remove from `/api/tools` active catalog.
5. Block graph execution and approval resume.
6. Remove API routes.
7. Remove integration status.
8. Rewrite/delete tests.
9. Update docs/dependencies/config.
10. Delete source file.
11. Run post-delete scans.

#### Reference Cleanup

- `src/mcp_gateway/registry.py`
- `src/api/server.py`
- `tests/test_p4_browser.py`
- `tests/test_mcp_gateway.py`
- `tests/test_real_tools.py`
- product/readiness/truthfulness tests.
- `docs/ARCHITECTURE.md`
- `docs/implementation-roadmap.md`
- `requirements.txt`
- `pyproject.toml`

#### Routes to Remove

- `POST /api/browser/browse`
- `POST /api/browser/screenshot`

#### Registry Cleanup

- Remove `safe_browse_url`.
- Remove `capture_screenshot`.
- Remove browser risk metadata.

#### HITL/Policy Cleanup

- Ensure browser tools are `blocked` during transition and absent at final state.

#### Frontend Cleanup

- Remove browser availability/status display.
- Remove active catalog entries.
- Keep removed/blocked history only in Tools Ops if useful.

#### Tests Proving Removal

- No `/api/browser/*` route.
- No browser sandbox tools in bindable registry.
- Static scan has no runtime references.

#### Config/Dependency Cleanup

- Remove backend Playwright dependency if not needed elsewhere.
- Do not remove frontend/browser test dependencies blindly if frontend tests still need them.

#### Rollback Plan

- Revert T3 deletion commit if app startup fails.

### Code Sandbox

#### Deletion Order

1. Add tests proving current exposure.
2. Add removed-tool metadata.
3. Remove from active registry and agent binding.
4. Remove from active `/api/tools`.
5. Block graph execution and approval resume.
6. Remove GitHub/code API routes.
7. Remove integration status.
8. Remove HITL previews/risk entries for removed GitHub sandbox tools.
9. Rewrite/delete tests.
10. Update docs/config.
11. Delete source file.
12. Run post-delete scans.

#### Reference Cleanup

- `src/mcp_gateway/registry.py`
- `src/api/server.py`
- `src/hitl/classifier.py`
- `src/hitl/approval_engine.py`
- `tests/test_p4_github.py`
- `tests/test_p6_security.py`
- `tests/test_e2e.py`
- `tests/test_hitl.py`
- product/readiness/truthfulness tests.
- README/docs.

#### Routes to Remove

- `POST /api/github/clone`
- `POST /api/github/commit_and_push`
- `POST /api/github/merge`

#### Registry Cleanup

- Remove `run_code`.
- Remove `github_clone`.
- Remove `github_commit_and_push`.
- Remove `github_merge`.

#### HITL/Policy Cleanup

- Remove or block GitHub sandbox tool names.
- Ensure old approval requests for removed tools cannot resume execution.

#### Tests Proving Removal

- No `/api/github/*` route.
- No code sandbox tools in bindable registry.
- No `src.mcp_gateway.sandboxes.code_sandbox` import.
- Static scan clean.

#### Config/Dependency Cleanup

- Remove docs advertising code execution.
- Remove any code-sandbox-only dependency if introduced later.

#### Rollback Plan

- Revert T3 deletion commit if app startup fails.

## 6. Personal OS Roadmap

### Exact Responsibilities

- Local task state.
- Local operator-visible actions.
- Local sub-agent state inspection/control, policy-gated.
- Local checkpoint metadata for HITL recovery.
- Local resource locks if still useful.
- Approved procedural workflow execution in bounded form.
- Audit and observability for local actions.

### Explicit Non-responsibilities

- No Gmail, WhatsApp, Telegram, Calendar, or search provider requests.
- No arbitrary browser access.
- No arbitrary code execution.
- No catch-all tool wrapper.
- No direct memory table writes outside approved memory repositories.
- No schedule recurrence ownership.

### Memory Integration

- Use semantic memory for stable facts/preferences through retrieval.
- Use structured episodes for past decisions/context through retrieval.
- Use procedural memory for approved workflows.
- Use summaries through context assembly.
- Enqueue memory jobs only for memory-side processing after approved actions.

### Semantic/Episodic/Procedural Usage Boundaries

- Read via retrieval or repositories.
- Write memory only through existing memory write services.
- Do not bypass semantic dedup, episodic store, procedural approval, or memory job queue.

### Approval Boundaries

- Reads: no approval.
- Local writes: confirmation recommended or approval required.
- Sub-agent lifecycle writes: approval required unless low-impact.
- Destructive actions: approval required or blocked.
- Scheduled actions: policy evaluated by cron and target tool.

### Local Task Model

Preserve task records, but add:

- typed status.
- idempotency for writes.
- audit IDs.
- ownership/session scope.
- policy metadata.

### Local Agent Lifecycle Model

Preserve read status. Gate pause/resume/terminate/spawn through policy. Record all lifecycle writes in audit.

### Checkpoint Model

Keep checkpointing for HITL. Refactor to store sufficient state references without raw hidden reasoning or unredacted payloads.

### Resource/Lock Model

Keep only if useful for concurrent local operations. Add owner, expiry, stale lock recovery, and audit.

### Audit Model

Use redacted `tool_calls`, `tool_results`, and `audit_logs`. Include idempotency key for write attempts.

### Idempotency Model

Action idempotency key includes tool ID, normalized payload hash, target resource, session/operator, and scheduled run ID if present.

### API Boundaries

- `GET /api/tools/personal-os/status`
- `GET /api/tools/personal-os/actions`
- `GET /api/tools/personal-os/audit`
- Preserve `GET /api/tasks` compatibility.

### Frontend Observability

Show:

- local tool availability.
- policy requirements.
- recent actions.
- failed actions.
- blocked synthetic/removed tools.

### Tests

- Policy for reads/writes.
- No provider direct calls.
- No synthetic tools unless justified.
- Memory-safe boundaries.
- Audit/idempotency.

### Must Not Include

Personal OS must not send Gmail, WhatsApp, Telegram, Calendar, or search provider requests directly.

## 7. Cron-job Roadmap

### Schedule Definition Model

Target `tool_schedules` fields:

- `id`
- `schedule_type`
- `cron_expression`
- `run_at`
- `timezone`
- `next_run_at`
- `last_run_at`
- `missed_run_policy`
- `max_catchup_runs`
- `target_tool_id`
- `target_payload_json`
- `approval_policy`
- `status`
- `created_by`
- `created_at`
- `updated_at`

### Run Attempt Model

Target `tool_schedule_runs` fields:

- `id`
- `schedule_id`
- `scheduled_for`
- `claimed_at`
- `started_at`
- `completed_at`
- `status`
- `attempt_count`
- `approval_request_id`
- `tool_call_id`
- `result_preview`
- `error_json`

### Persistence

Use SQLite tables and idempotent migrations. Preserve old `scheduled_jobs` until compatibility is retired.

### One-time Jobs

Use `schedule_type = one_time` and `run_at`. Mark completed after success.

### Recurring Jobs

Use `schedule_type = recurring`, cron parser, timezone, and `next_run_at`.

### Cron Parser

Use a real parser with deterministic tests. Reject unsupported syntax.

### Timezone

Store configured timezone and UTC timestamps. Tests must inject deterministic `now`.

### `next_run_at` / `last_run_at`

Poll due schedules by `next_run_at`, never by lexicographic cron string comparison.

### Missed-run Policies

- `skip`
- `run_once`
- `catch_up_limited`

### Execution Boundary

Due jobs invoke target tools only through unified tool invocation and policy.

### Approval and Preapproval

- Read-only scheduled action may run if schedule was authorized.
- Write/external/destructive scheduled action requires approval at execution unless durable preapproval is explicitly implemented.

### Cancellation/Update

Cancel future runs without deleting history. Updates recalculate next run and may require approval.

### Retry/Dead-letter or Failed-terminal Handling

Tool run attempts can retry transient failures. Exhausted failures become `FAILED_TERMINAL`. A separate dead-letter table can be added if needed, but run history may be enough for scheduler v1.

### Observability

Expose schedule state, run attempts, approvals, failures, next/last run, and missed-run policy.

### Frontend

`ScheduledCockpit` shows typed schedule state and run history.

### Tests

One-time, recurring, timezone, missed-run, retry, cancel/update, approval, no `memory_jobs` overload.

### Relationship With Google Calendar MCP

Calendar events are provider records. Cron can schedule an action that calls Google Calendar MCP after approval, but Calendar MCP does not replace cron.

### Relationship With Personal OS

Cron schedules Personal OS actions; Personal OS executes bounded local actions.

### Why It Must Not Overload `memory_jobs`

`memory_jobs` is for memory architecture work. Scheduler definitions need recurrence/timezone/action/approval state and should remain separate.

## 8. MCP Wiring Roadmap

### A. Tavily / DuckDuckGo Search MCP

- Provider responsibility: search execution, ranking/snippets, provider credentials.
- Local responsibility: discover, register, route, policy-gate, observe.
- Config/env validation: validate MCP server config; do not call Tavily REST directly.
- Transport/manual validation: confirm stdio/SSE/HTTP/app connector.
- Discovery check: `tools/list` returns expected search tool.
- Registration check: tool is provider-managed/read-only/external.
- Routing check: primary agent can bind when available.
- Approval policy check: normally no approval; confirmation recommended for sensitive query payloads.
- Provider unavailable behavior: hide from bindable tools and show status.
- Observability check: query preview only, no secrets.
- Tests: mocked MCP search provider, unavailable provider, no local `perform_web_search`.
- Local adapter replacement/removal: replace `search.py` wrapper, delete `search_adapters.py` after compatibility.
- Manual validation steps: safe query smoke test against configured provider.

### B. Google Calendar MCP

- Provider responsibility: calendar read/write, provider permissions, event IDs.
- Local responsibility: metadata, approval, wrapper compatibility, audit.
- Config/env validation: MCP provider config/OAuth, no direct `GOOGLE_CALENDAR_TOKEN` REST path.
- Transport/manual validation: confirm provider server and scopes.
- Discovery check: event read/create/update/delete tools discovered.
- Registration check: reads no approval; writes approval required.
- Routing check: primary agent binds available calendar tools.
- Approval policy check: create/update/delete and external invite changes require approval.
- Provider unavailable behavior: safe unavailable status.
- Observability check: event previews redacted.
- Tests: mocked MCP calendar provider, approval-required writes, no SQLite CRUD as source of truth.
- Local adapter replacement/removal: convert `calendar.py` to thin boundary or remove; delete/deprecate `google_calendar_sync.py`.
- Manual validation steps: read-only calendar list, then dry-run or approval-gated test event in safe calendar.

### C. WhatsApp MCP

- Provider responsibility: WhatsApp read/send/delivery.
- Local responsibility: discovery, routing, external communication approval, audit/redaction.
- Config/env validation: MCP config; no direct Meta REST.
- Transport/manual validation: confirm account identity and send scope.
- Discovery check: read/send tools.
- Registration check: send external/high-risk.
- Routing check: primary agent only.
- Approval policy check: send approval required.
- Provider unavailable behavior: hide tools/status unavailable.
- Observability check: message previews truncated/redacted.
- Tests: mocked provider, send approval, no `WHATSAPP_API_TOKEN` REST call.
- Local adapter replacement/removal: replace WhatsApp sections in `communication.py`.
- Manual validation steps: safe test recipient only after approval flow.

### D. Telegram MCP

- Provider responsibility: Telegram read/send/delivery.
- Local responsibility: discovery, routing, approval, audit.
- Config/env validation: MCP config; no direct Bot API call.
- Transport/manual validation: bot/user mode and chat ID behavior.
- Discovery check: read/send tools.
- Registration check: send external/high-risk.
- Routing check: primary agent only.
- Approval policy check: send approval required.
- Provider unavailable behavior: safe unavailable state.
- Observability check: chat/message preview redacted.
- Tests: mocked provider, send approval, no `TELEGRAM_BOT_TOKEN` REST call.
- Local adapter replacement/removal: replace Telegram sections in `communication.py`.
- Manual validation steps: safe test chat after approval flow.

### E. Gmail MCP

- Provider responsibility: Gmail read/search/draft/send/thread/labels as exposed.
- Local responsibility: discovery, routing, approval, redacted audit.
- Config/env validation: MCP/OAuth config; no SMTP/IMAP local path.
- Transport/manual validation: scopes and tool schemas.
- Discovery check: read/search/draft/send tools.
- Registration check: read/search no approval, draft confirmation recommended, send approval required.
- Routing check: primary agent only.
- Approval policy check: send approval required with preview.
- Provider unavailable behavior: hide tools and show status.
- Observability check: no full body by default.
- Tests: mocked provider, send approval, no `smtplib`/`imaplib`.
- Local adapter replacement/removal: remove `email_adapters.py`, replace email section in `communication.py`.
- Manual validation steps: list messages in test account; create draft/send only after approval.

## 9. Local Adapter Migration Roadmap

| File | Temporary State | Target State | Replacement MCP Path | Tests to Rewrite | Decision | Risks |
|---|---|---|---|---|---|---|
| `src/mcp_gateway/search.py` | Legacy wrapper available until MCP search passes | Thin MCP search route or removed | Search MCP invocation | `test_p4_search.py`, `test_real_tools.py` | Convert then maybe keep wrapper | API formatting compatibility |
| `src/mcp_gateway/search_adapters.py` | Legacy direct Tavily/DDG | Removed | Provider-managed Search MCP | `test_p4_search.py`, `test_p5_real_provider_integrations.py` | Delete | Loss of local fallback |
| `src/mcp_gateway/calendar.py` | Legacy SQLite/REST calendar | Thin Google Calendar MCP boundary or removed | Google Calendar MCP invocation | `test_p4_calendar.py`, API tests | Convert/remove local CRUD | Existing local calendar rows |
| `src/mcp_gateway/google_calendar_sync.py` | Simulated sync | Removed/deprecated migration aid | Google Calendar MCP | `test_p4_calendar.py` | Delete unless cache migration needed | Users expecting local sync |
| `src/mcp_gateway/communication.py` | Legacy email/WA/TG local adapter | Split thin MCP wrappers or remove | Gmail/WhatsApp/Telegram MCP | `test_mcp_gateway.py`, `test_p4_email.py`, real provider tests | Convert then prune | Many tool names depend on it |
| `src/mcp_gateway/email_adapters.py` | SMTP/IMAP local adapter | Removed | Gmail MCP | `test_p4_email.py`, provider integration tests | Delete | Email API compatibility |

Old local tables (`calendar_events`, `emails`, `whatsapp_messages`, `telegram_messages`) should remain until a later schema cleanup decision. In this roadmap they may be preserved as audit/cache only if explicitly documented, but not as provider source of truth.

## 10. Safety and Policy Roadmap

### Read-only Tools

Execute directly if provider/local resource is available and request scope is safe. Audit optional except for provider calls.

### Low-risk Writes

Allow direct execution or confirmation recommended. Always audit.

### High-risk Writes

Require HITL approval.

### External Communication Policy

Gmail send, WhatsApp send, and Telegram send require approval with preview.

### Destructive Action Policy

Require approval or block. Removed sandbox actions are blocked.

### Scheduled Future Action Policy

Evaluate policy at schedule creation and run execution. High-risk future writes require approval unless a durable preapproval model is explicitly implemented.

### Removed Tool Blocking

Removed tools are not bindable and cannot be resumed from old approvals.

### Provider-managed Confirmation

Local HITL complements, but does not bypass, provider-managed confirmation/OAuth/permission checks.

### Audit Trail Expectations

Every write, external call, scheduled run, approval, failure, and blocked removed-tool attempt is audited with redaction.

### Approval Preview Requirements

Previews must include target, action, key arguments, and redacted/truncated content. Never expose secrets or hidden reasoning.

### Approval Resume Safety

Resume must revalidate:

- tool still exists.
- tool is not removed.
- provider is available.
- policy still permits execution.
- request has not already executed.

## 11. Tool Routing Roadmap

### Primary Agent Bindable Tools

Bindable tools are enabled, available, policy-known tools from:

- Personal OS local layer.
- cron-job local scheduler.
- provider-managed MCP registry.

### Unavailable MCP Provider Behavior

Unavailable tools are hidden from primary binding and shown in status/observability.

### Removed Tools Not Bindable

Removed tools never appear in the primary bindable tool list.

### Secondary Memory Worker Prohibition

Memory workers and secondary LLM handlers must not import or bind user-facing tools.

### Role-aware Registry Tests

Tests must assert primary route can bind tools and secondary route cannot.

### Graph Integration Tests

Graph tests cover normal tool calls, provider unavailable, removed blocked, and approval pause.

### Approval Pause/Resume Tests

Approval resume must support MCP and cron context, and block removed tools.

### Tool Error Normalization

Tool errors normalize to safe classes: provider unavailable, validation, policy denied, approval required, removed, retryable, terminal.

## 12. API Roadmap

### Unified `/api/tools` Catalog

Keep compatibility while adding groups for:

- local.
- cron.
- provider-managed MCP.
- unavailable.
- removed/blocked.

### `/api/tools/status`

Registry health, provider counts, policy readiness, and removed-tool count.

### MCP Provider Status

- `GET /api/tools/mcp/providers`
- `GET /api/tools/mcp/providers/{provider_id}`
- optional explicit discovery refresh if approved.

### Personal OS Status/Actions/Audit

- `GET /api/tools/personal-os/status`
- `GET /api/tools/personal-os/actions`
- `GET /api/tools/personal-os/audit`

### Cron Schedules/Runs

- `GET /api/tools/cron/schedules`
- `POST /api/tools/cron/schedules`
- `GET /api/tools/cron/schedules/{schedule_id}`
- `PATCH /api/tools/cron/schedules/{schedule_id}`
- `DELETE /api/tools/cron/schedules/{schedule_id}`
- `GET /api/tools/cron/runs`

### Tool Observability

- `GET /api/tools/observability/overview`
- `GET /api/tools/observability/calls`
- `GET /api/tools/observability/results`
- `GET /api/tools/observability/audit`
- `GET /api/tools/observability/blocked`

### Removed/Deprecated Routes

Remove or temporarily deprecate:

- `/api/browser/*`
- `/api/github/*`

### API Compatibility Tests

Retained endpoints keep response shapes. Removed endpoints have explicit tests.

## 13. Frontend Roadmap

### Tools Catalog Update

Show grouped local, cron, MCP, unavailable, and removed tools.

### ScheduledCockpit Redesign

Support one-time/recurring schedules, timezone, next/last run, missed-run policy, approval, run history, retry/failure display.

### ApprovalInbox Compatibility

Support existing approvals plus MCP and cron approval metadata.

### Overview Text Cleanup

Remove "22 OS + MCP Gateway" and sandbox claims.

### Tools Ops Panel

Add a read-only operations panel for registry, provider status, audit, blocked attempts, Personal OS, and cron.

### MCP Provider Status

Show configured/unconfigured, discovery state, available tools, last error.

### Personal OS Operations

Show bounded tools, policy, recent actions, failures.

### Cron Schedules/Runs

Show definitions and run attempts.

### Tool Audit

Show redacted calls/results/audit.

### Removed Tool Visibility

Only show removed tools in ops/blocked view, never as available.

### Frontend Tests/Build

Smoke render, API fetch mocks, empty/error states, no removed route calls, `npm run build`.

## 14. Testing Roadmap

### Baseline Tests

T0 captures current exposure and config unknowns.

### Registry Tests

Implementation type, provider-managed flag, removed not bindable, metadata completeness.

### Sandbox Removal Tests

No active exposure, no routes, no imports, static scans clean.

### Personal OS Tests

Bounded responsibilities, policy, no provider direct calls, memory-safe boundaries.

### Cron Tests

Persistence, recurrence, timezone, missed runs, retries, cancellation, approval, no `memory_jobs` overload.

### MCP Discovery Tests

Mock target providers and validate discovery/registration/schema normalization.

### MCP Provider Unavailable Tests

Unavailable providers do not break chat and are hidden from binding.

### No Duplicate Provider Implementation Tests

Static scans and monkeypatches prove no direct Tavily/DDG/Calendar/Gmail/WhatsApp/Telegram implementation is used.

### HITL Policy Tests

All high-risk classes require approval; removed tools blocked.

### Primary-only Routing Tests

Primary binds available tools; secondary cannot.

### Secondary LLM Cannot Call User-facing Tools Tests

Scans and monkeypatches in memory handlers/worker.

### Frontend Smoke Tests

Tools catalog, Tools Ops, Scheduled, Approval, Overview.

### API Compatibility Tests

Retained endpoint shapes and removed route behavior.

### E2E Tests

Chat with no providers, mocked MCP read tool, approval-gated external send, cron due read/write, Personal OS actions, observability.

### Static Scans

All Section 18 scans in final phase and relevant subsets each phase.

## 15. Documentation Roadmap

Add/update:

- `docs/tools-architecture.md`
- `docs/tools-operator-runbook.md`
- `docs/tools-mcp-wiring.md`
- `docs/tools-security-policy.md`
- `docs/tools-cron-jobs.md`
- `docs/tools-personal-os.md`
- `README.md`
- `.env.example`
- `.agent/mcp_config.json` example guidance, preferably as documented example rather than committing secrets.

Docs must explain:

- local versus MCP tool taxonomy.
- provider-managed MCP rule.
- Personal OS boundaries.
- cron versus Google Calendar.
- HITL policy.
- approval previews.
- observability/redaction.
- manual provider validation.
- sandbox removal proof.

## 16. Final Acceptance Criteria

The tools migration is complete when:

- browser sandbox is fully removed.
- code sandbox is fully removed.
- no references to removed tools remain.
- Personal OS tools are memory-architecture aware and bounded.
- cron-job is durable and tested.
- MCP tools are correctly discovered, registered, and routed.
- no local duplicate MCP provider implementations exist.
- tool routing works through the primary agent only.
- secondary LLM cannot invoke user-facing tools.
- high-risk actions require HITL approval.
- removed tools are blocked and not resumable through old approvals.
- frontend reflects final tool architecture.
- observability exposes safe tool status.
- full backend test suite passes.
- frontend build passes.
- docs are complete.

## 17. Static Scan Commands

```powershell
rg -n "browser sandbox|browser_sandbox|sandbox_browser|safe_browse_url|capture_screenshot|playwright|selenium|code sandbox|code_sandbox|python sandbox|run_code|exec_code|github_clone|github_commit_and_push|github_merge|/api/browser|/api/github" src frontend tests docs README.md pyproject.toml requirements.txt

rg -n "Tavily|DuckDuckGo|Calendar|WhatsApp|Telegram|Gmail|MCP|tool registry|ToolRegistry|cron|scheduler|reminder" src frontend tests docs README.md .env.example .agent/mcp_config.json

rg -n "resolve_secondary_llm|get_secondary_llm|\.invoke\(" src/tools src/personal_os src/mcp_gateway src/harness src/api src/memory

rg -n "create_approval_request|approval_required|policy_check|AskPermission|HITL" src/tools src/personal_os src/mcp_gateway src/harness src/api src/hitl

rg -n "TAVILY_API_KEY|SMTP_|IMAP_|WHATSAPP_API_TOKEN|TELEGRAM_BOT_TOKEN|GOOGLE_CALENDAR_TOKEN|requests\.post|requests\.get|smtplib|imaplib|duckduckgo_search|DDGS" src/mcp_gateway src/api tests docs README.md .env.example
```

Because `src/tools` does not exist at the start of this migration, early-phase scans should omit it or allow it to be absent until T1 introduces the tools package.

