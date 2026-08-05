# Tools Architecture Migration Blueprint

Generated from:

- `docs/tools-gap-analysis.md`
- current codebase in `D:\agent`
- completed memory architecture
- existing HITL approval system
- existing memory observability system
- existing frontend tool, approval, and scheduled-job panels

This blueprint is design-only. It does not implement code, delete files, or modify runtime behavior.

## 1. Executive Summary

The target tools architecture separates local tools from provider-managed MCP tools.

Final tool categories:

- Non-MCP local tools:
  - Personal OS tools
  - cron-job tool
- Provider-managed MCP tools:
  - Tavily or DuckDuckGo Search MCP
  - Google Calendar MCP
  - WhatsApp MCP
  - Telegram MCP
  - Gmail MCP
- Removed tools:
  - browser sandbox
  - code sandbox

The completed memory architecture should become the design foundation for tool safety and operations, not a dumping ground for tool execution. Memory remains responsible for durable memory jobs, summaries, structured episodes, semantic memory, procedural skills, adaptive retrieval, and memory observability. Tools remain responsible for user-facing actions, provider interactions, local assistant operations, scheduling, approval, audit, and operator visibility.

The main architectural correction is to stop treating local provider adapters as MCP tools. MCP tools are provider-managed. Local code should only handle discovery, registration, metadata exposure, routing, permission and HITL policy, invocation boundaries, error handling, observability, and frontend status display.

The migration should be evolutionary, but firm:

1. Separate registry and policy before removing anything.
2. Block and remove browser/code sandboxes only after references are cleaned.
3. Redesign Personal OS as a bounded local non-MCP tool layer.
4. Fix cron as a durable scheduler, separate from memory job definitions.
5. Replace local provider implementations with provider-managed MCP wiring.
6. Add unified routing, approval policy, audit, observability, frontend support, and E2E hardening.

## 2. Current State Summary

Important findings from `docs/tools-gap-analysis.md`:

- Local adapters are mislabeled as MCP tools.
  - `src/mcp_gateway/search.py` and `src/mcp_gateway/search_adapters.py` implement Tavily REST, DuckDuckGo library usage, and local fallback.
  - `src/mcp_gateway/calendar.py` implements local SQLite calendar CRUD and optional direct Google REST.
  - `src/mcp_gateway/communication.py` implements email, WhatsApp, and Telegram behavior through SQLite, SMTP/IMAP, or REST.
  - These should not remain provider implementations for the target MCP architecture.
- Browser and code sandboxes are deeply wired.
  - They are imported by `src/mcp_gateway/registry.py` and `src/api/server.py`.
  - They are exposed through API routes, catalog/status endpoints, tests, docs, and dependencies.
  - No tracked runtime sandbox file is safe to delete before reference cleanup.
- Personal OS needs redesign.
  - It currently exposes 22 tools with broad direct SQLite writes.
  - It has weak policy metadata and is not memory-aware.
  - Synthetic tools such as `sleep`, `wake`, `subscribe_event`, `acquire_context`, and `release_context` do not have clear target responsibilities.
- Cron-job is defective.
  - It stores schedule rows but does not implement real cron semantics.
  - Cron expressions are compared as timestamps.
  - Recurrence, missed-run handling, timezones, run attempts, and structured execution are missing.
- Approval policy is inconsistent.
  - `src/hitl/classifier.py` and `src/mcp_gateway/registry.py` have separate risk maps.
  - Some write-capable tools are Low risk in one place and High risk in another.
  - Some API routes bypass graph HITL entirely.
- MCP provider wiring is unknown.
  - `.agent/mcp_config.json` configures demo/local providers, not the target providers.
  - The target provider credential and transport model needs manual validation.

## 3. Target Tool Taxonomy

### A. Non-MCP Local Tools

#### Personal OS

Personal OS is the local assistant operations layer. It owns local, non-provider-managed actions that operate on assistant state, task state, local operator workflows, safe local reminders, and approved local process controls.

#### cron-job

cron-job is the local durable scheduler. It owns schedule definitions, recurrence calculation, next-run state, run attempts, missed-run behavior, cancellation, and execution handoff.

### B. Provider-managed MCP Tools

Provider-managed MCP tools are discovered and invoked through MCP provider servers/connectors. Local code must not duplicate provider behavior.

Target providers:

- Tavily or DuckDuckGo Search MCP
- Google Calendar MCP
- WhatsApp MCP
- Telegram MCP
- Gmail MCP

### C. Removed Tools

The following tools are removed completely:

- browser sandbox
- code sandbox

Removal includes tool functions, registry entries, API routes, integration status entries, tests, docs, and dependencies when no longer needed.

## 4. Personal OS Architecture

### Objective

Personal OS becomes the main local non-MCP tool layer. It should be explicit, bounded, auditable, approval-aware, and compatible with the completed memory architecture.

### Exact Responsibilities

Personal OS should own:

- Local assistant task state.
- Local operator-visible work items.
- Local action plans that do not belong to external providers.
- Safe local state inspection.
- Local resource coordination and locks, if still needed.
- Checkpoint/readback helpers required by HITL.
- Local workflow execution only when explicitly approved and bounded.
- Integration with procedural memory for approved local workflows.
- Memory-aware context use through retrieval, not synthetic context writes.
- Local audit records for Personal OS actions.
- Tool metadata for local tools.

### Explicit Non-responsibilities

Personal OS must not:

- Reimplement MCP provider functions.
- Send Gmail, WhatsApp, Telegram, or Calendar provider requests directly.
- Browse arbitrary web pages.
- Execute arbitrary code.
- Become a catch-all for unclassified tools.
- Write semantic, episodic, or procedural memory directly except through approved memory repositories or memory jobs.
- Start background workers automatically.
- Bypass HITL for risky actions.
- Create synthetic context that competes with adaptive retrieval.

### Tool Boundaries

Personal OS tools should be grouped into explicit namespaces:

| Namespace | Purpose | Examples | Status |
|---|---|---|---|
| `personal_os.task.*` | Local task records | create, update, cancel, list | Redesign |
| `personal_os.agent.*` | Local sub-agent lifecycle | status, pause, resume, terminate | Redesign and policy-gate |
| `personal_os.checkpoint.*` | HITL recovery state | create, read, restore | Preserve then refactor |
| `personal_os.resource.*` | Local coordination locks | acquire, release, inspect | Redesign |
| `personal_os.workflow.*` | Approved local workflow execution | run approved procedural skill | Future bounded path |
| `personal_os.health.*` | Local status | heartbeat, readiness | Preserve |

The following current tools should be removed or replaced unless a concrete purpose is approved:

- `sleep`
- `wake`
- `subscribe_event`
- current synthetic `acquire_context`
- current synthetic `release_context`

### Registry Shape

Personal OS registry entries should use the unified metadata model described in Section 8. Each tool must declare:

- stable `tool_id`
- provider `local`
- implementation type `local`
- risk class
- approval policy
- read/write capability
- whether it can be scheduled
- audit payload schema
- idempotency strategy
- observability view

### API Shape

Existing APIs can be preserved initially:

- `GET /api/tasks`
- `GET /api/tools`
- `GET /api/approvals`
- `POST /api/approvals/{request_id}/decision`

Additive or migrated Personal OS APIs should be grouped under:

- `GET /api/tools/personal-os/status`
- `GET /api/tools/personal-os/actions`
- `GET /api/tools/personal-os/audit`
- `POST /api/tools/personal-os/actions/{action_id}` for explicit operator actions if needed

Write APIs should use a consistent policy evaluator before execution.

### Frontend Observability Shape

The existing Tools Catalog and Approval Inbox should be extended into a Tools Ops surface:

- Personal OS status.
- Available local tools.
- Disabled or removed local tools.
- Approval requirements.
- Recent Personal OS actions.
- Failed actions.
- Idempotency keys and audit IDs where safe.

### Allowed Actions

Allowed with no approval:

- Read local task list.
- Read local agent status.
- Read heartbeat/readiness.
- Read local checkpoint metadata.
- Inspect approved procedural skill metadata.

Allowed with confirmation or approval depending scope:

- Create local task.
- Update local task.
- Cancel local task.
- Acquire/release local lock.
- Pause/resume/terminate sub-agent.
- Execute approved local procedural workflow.

Blocked:

- Arbitrary code execution.
- Browser sandbox fetch/screenshot.
- Unscoped filesystem mutation.
- Direct provider communication.
- Direct memory table writes outside approved repositories.

### Approval Policy

Personal OS approval should use the consolidated policy model:

- Read-only inspection: no approval.
- Local state write: confirmation recommended or approval required depending impact.
- Sub-agent launch/control: approval required unless scoped to low-risk read-only work.
- Destructive local action: approval required or blocked.
- Scheduled future action: approval required at schedule creation and possibly execution.

### Relationship With Memory Retrieval

Personal OS may use memory through retrieval and approved repository APIs:

- Semantic memory can inform stable user facts/preferences.
- Episodic memory can inform past decisions/context.
- Procedural memory can provide approved workflows.
- Summary blocks can provide long-session context.

Personal OS must not create its own synthetic context layer. The current `context_blocks` approach should be retired or repurposed only as an audit/cache table if a later phase justifies it.

### Relationship With Memory Jobs

Personal OS should not overload `memory_jobs` for local tool execution. It may enqueue memory jobs only when a Personal OS action generates memory-relevant events that need background processing. Example: a completed approved workflow may enqueue semantic or episodic memory processing through the existing memory job API.

### Relationship With Cron-job

Cron owns scheduling. Personal OS owns local action execution. A scheduled Personal OS action should be represented as:

1. cron schedule definition.
2. due run attempt.
3. policy evaluation.
4. Personal OS action invocation if allowed.
5. audit and observability record.

### Relationship With MCP Tools

Personal OS may schedule or coordinate MCP actions, but it must not implement provider behavior. If a scheduled action targets Gmail, Calendar, WhatsApp, Telegram, or search, cron should hand off to the MCP invocation boundary after policy approval.

### Audit Model

Each Personal OS action should produce:

- tool call ID.
- session or operator scope.
- tool ID.
- normalized input payload preview.
- redacted full payload where allowed.
- approval ID if applicable.
- result status.
- result preview.
- error class.
- created_at and completed_at.

Existing `tool_calls`, `tool_results`, `audit_logs`, and `loop_events` can be preserved and extended.

### Idempotency Model

Write-capable Personal OS actions should use deterministic idempotency keys when the action is retryable or approval-gated. The key should include:

- tool ID.
- session/operator scope.
- normalized payload hash.
- target resource ID where applicable.
- scheduled run ID if invoked by cron.

### Error Handling

Errors should be classified as:

- validation error.
- policy denied.
- approval required.
- provider unavailable, when routed through MCP.
- conflict.
- retryable transient error.
- terminal failure.

User-facing errors should be concise. Observability can include redacted diagnostic detail.

## 5. Cron-job Architecture

### Objective

cron-job becomes a reliable local scheduler for assistant actions. It is not Google Calendar. Google Calendar is for calendar events; cron-job is for scheduled assistant actions.

### Existing Table or New Scheduler Tables

Use new scheduler tables rather than overloading the existing `scheduled_jobs` shape. The current table can be preserved for compatibility during migration, then replaced or migrated.

Recommended tables:

- `tool_schedules`
- `tool_schedule_runs`
- `tool_schedule_locks`

`scheduled_jobs` can remain temporarily as a legacy read source or compatibility view, but target code should not depend on the old `cron_or_timestamp` string as both definition and due state.

### Why Not Use `memory_jobs` as Schedule Definitions

`memory_jobs` is for background memory processing. Schedule definitions need recurrence state, timezone, missed-run policy, action target, approval policy, and run history. These are not memory processing concerns.

Cron may enqueue `memory_jobs` only when a due action creates memory-side work, but schedule definitions belong in scheduler tables.

### One-time Job Model

A one-time job stores:

- schedule_id.
- schedule_type `one_time`.
- run_at.
- timezone.
- action_type.
- target_tool_id.
- target_payload_json.
- approval_policy.
- status.
- created_by.
- created_at.

After successful execution, status becomes `completed`. If cancelled before execution, status becomes `cancelled`.

### Recurring Job Model

A recurring job stores:

- schedule_type `recurring`.
- cron_expression.
- timezone.
- next_run_at.
- last_run_at.
- missed_run_policy.
- max_catchup_runs.
- status.
- action metadata.

Each due occurrence creates a row in `tool_schedule_runs`.

### Cron Expression Parsing

Use a real cron parser. Do not compare cron strings lexicographically to timestamps. The parser must:

- validate expressions at creation.
- compute next run in the configured timezone.
- support deterministic tests through injected `now`.
- reject unsupported syntax explicitly.

### Timezone Handling

Each schedule must store a timezone. Default should be the configured application timezone or user profile timezone. Store computed run timestamps in UTC plus the original timezone.

### `next_run_at` and `last_run_at`

`tool_schedules.next_run_at` is authoritative for due polling. `last_run_at` is updated after a run is claimed or completed according to the selected policy.

### Missed-run Policy

Supported policies:

- `skip`: skip missed occurrences and schedule the next future run.
- `run_once`: create one catch-up run for the latest missed occurrence.
- `catch_up_limited`: create up to `max_catchup_runs`.

Default should be `run_once` for reminders and `skip` for high-risk external writes unless explicitly approved.

### Retry Behavior

Run attempts should support:

- `PENDING`
- `CLAIMED`
- `WAITING_FOR_APPROVAL`
- `RUNNING`
- `SUCCEEDED`
- `FAILED_RETRYABLE`
- `FAILED_TERMINAL`
- `CANCELLED`

Retry policy belongs to run attempts, not schedule definitions.

### Cancellation and Update

Cancellation:

- cancels future runs.
- does not delete history.
- may cancel pending run attempts.

Update:

- creates a new schedule version or records an update audit.
- recalculates `next_run_at`.
- requires approval if action risk increases.

### Persistence Across Restart

Scheduler state persists in SQLite. Startup should not automatically execute due jobs unless the worker is explicitly configured to run. A dedicated scheduler worker entrypoint can process due jobs.

### Execution Boundary

Due execution flow:

1. Claim due schedule/run with deterministic lock.
2. Evaluate policy.
3. If approval required, create HITL approval and mark `WAITING_FOR_APPROVAL`.
4. If approved or direct, invoke the target tool through the unified tool invocation boundary.
5. Record result in run history and tool audit.
6. Compute next run for recurring schedules.

### Approval Requirements

- Creating a schedule for a read-only action: no approval or confirmation recommended.
- Creating a schedule for local writes: confirmation recommended or approval required.
- Creating a schedule for external communication: approval required.
- Execution of high-risk scheduled actions: approval required unless a durable preapproval policy exists.
- Schedule update/delete: approval required if it affects high-risk actions.

### Observability

Expose:

- schedule definitions.
- next/last run.
- timezone.
- missed-run policy.
- pending approvals.
- run attempts.
- failures.
- disabled/cancelled state.

### Frontend Display

Replace the simple `cron_or_timestamp` panel with:

- schedule type.
- human-readable next run.
- timezone.
- recurrence.
- action target.
- approval state.
- last result.
- missed-run policy.
- run history.

### Interaction With Google Calendar MCP

Google Calendar MCP is not the scheduler. Calendar events can be created or updated by scheduled actions only through the MCP invocation boundary and approval policy.

### Interaction With Personal OS

Cron can schedule Personal OS actions. Personal OS does not own recurrence calculation.

## 6. MCP Tool Architecture

### Shared MCP Design

For every provider-managed MCP tool, local code owns only:

- provider discovery.
- MCP registration.
- tool metadata exposure.
- routing.
- permission/HITL policy.
- invocation boundary.
- error handling.
- observability.
- frontend status display.

Local code must not implement provider-specific behavior such as sending emails, sending messages, creating calendar events, or executing search APIs.

### Discovery Flow

1. Read configured MCP providers.
2. Start or connect to provider MCP server.
3. Perform initialize handshake.
4. Call `tools/list`.
5. Normalize returned tools into local metadata.
6. Apply local policy overlays.
7. Expose available tools to the primary agent and frontend.

### Registration Flow

Registration should produce a stable local `tool_id` that maps to:

- provider ID.
- MCP server ID.
- MCP tool name.
- normalized display name.
- risk class.
- approval policy.
- availability status.

### Invocation Boundary

Invocation should:

- validate provider availability.
- validate tool arguments against MCP input schema if available.
- apply local policy.
- create HITL request if required.
- invoke provider MCP tool only after policy permits.
- capture redacted result.
- persist audit.
- surface safe errors.

### Tavily / DuckDuckGo Search MCP

Provider responsibility:

- Search execution.
- Search ranking/snippets.
- Provider-specific credentials and query handling.

Local responsibility:

- Discover either Tavily or DuckDuckGo MCP tools.
- Register search tool metadata.
- Route user search requests from primary LLM.
- Mark as read-only external tool.
- Capture source status and errors.

Expected config/env model:

- MCP server entry for Tavily or DuckDuckGo.
- Provider credentials as required by the MCP server.
- Local code should not read `TAVILY_API_KEY` to call Tavily REST directly.

Permission policy:

- General web search: no approval needed.
- Sensitive or private-data query: confirmation recommended if query includes personal secrets.

HITL:

- Usually not required.

Observability/frontend:

- Provider configured/unconfigured.
- Discovery success/failure.
- Tool count.
- Last error.
- Last invocation status, with query preview only.

Manual validation:

- Which MCP provider/server is available.
- Transport type and credential names.
- Whether both Tavily and DuckDuckGo can be configured and how priority is selected.

### Google Calendar MCP

Provider responsibility:

- Calendar read/write behavior.
- Event creation/update/delete.
- Conflict handling if provider supports it.
- OAuth or provider credential model.

Local responsibility:

- Discover calendar tools.
- Normalize read/write metadata.
- Apply approval policy.
- Preserve API compatibility where needed through thin wrappers.
- Store audit, not provider source-of-truth data unless approved as cache.

Expected config/env model:

- Google Calendar MCP server configuration.
- Provider-managed OAuth/credentials.
- Local `.env` should not drive direct Google REST calls.

Permission policy:

- Calendar read: no approval.
- Calendar create/update/delete: approval required.
- Inviting attendees or modifying external guests: approval required with preview.

Observability/frontend:

- Provider connected.
- Calendar scopes available.
- Read/write capability.
- Last discovery and invocation errors.
- Pending approvals.

Manual validation:

- Available MCP tool names.
- OAuth/scopes required.
- Whether provider exposes dry-run or conflict-check tools.

### WhatsApp MCP

Provider responsibility:

- Sending/reading WhatsApp messages.
- Provider authentication.
- Message delivery status.

Local responsibility:

- Discover WhatsApp MCP tools.
- Register read/send capability.
- Apply external communication policy.
- Redact message body previews.
- Audit invocation and approval.

Expected config/env model:

- WhatsApp MCP server configuration.
- Provider-managed credentials.

Permission policy:

- Read messages: no approval or confirmation recommended depending privacy scope.
- Send message: approval required.

Observability/frontend:

- Provider connected/unavailable.
- Read/send capability.
- Pending outbound approvals.
- Redacted last-error details.

Manual validation:

- Target WhatsApp MCP availability.
- Required identity/account configuration.
- Delivery status behavior.

### Telegram MCP

Provider responsibility:

- Telegram read/send behavior.
- Bot or account credential handling.
- Delivery status.

Local responsibility:

- Discover Telegram MCP tools.
- Apply policy and audit.
- Redact content.
- Surface availability.

Expected config/env model:

- Telegram MCP server configuration.
- Provider-managed token/account model.

Permission policy:

- Read messages: no approval or confirmation recommended depending scope.
- Send message: approval required.

Manual validation:

- MCP provider tool names.
- Whether chat IDs are resolved by provider or supplied by user.
- Bot versus user account mode.

### Gmail MCP

Provider responsibility:

- Gmail read/search/draft/send behavior.
- OAuth/scopes.
- Message IDs, drafts, threads, labels.

Local responsibility:

- Discover Gmail MCP tools.
- Register read/search/draft/send metadata.
- Apply approval policy.
- Redact subjects/bodies in observability.
- Preserve API compatibility only through thin wrappers if needed.

Expected config/env model:

- Gmail MCP server configuration.
- Provider-managed OAuth.
- SMTP/IMAP environment variables should be removed or deprecated after migration.

Permission policy:

- Gmail read/search: no approval or confirmation recommended depending privacy.
- Gmail draft: confirmation recommended.
- Gmail send: approval required.
- Delete/archive/label changes if exposed: approval required or confirmation recommended depending impact.

Manual validation:

- Provider MCP availability.
- OAuth scopes.
- Draft/send semantics.
- Attachment behavior, if exposed.

## 7. MCP Migration From Current Local Adapters

| Current file | Decision | Reason | Risks |
|---|---|---|---|
| `src/mcp_gateway/search.py` | Convert to thin MCP routing wrapper or remove | Current `search_web` is a local tool over local adapters. Target search is provider-managed MCP. | Existing `/api/search` and graph tests may expect formatted local output. |
| `src/mcp_gateway/search_adapters.py` | Remove after MCP search route is stable | It directly calls Tavily REST and DuckDuckGo library. This violates provider-managed MCP rule. | Loss of local fallback if MCP provider unavailable. Use provider unavailable response instead. |
| `src/mcp_gateway/calendar.py` | Convert to thin MCP boundary or remove local CRUD | Current SQLite/REST CRUD duplicates Google Calendar provider behavior. | Existing calendar API/tests depend on local rows. Need compatibility transition. |
| `src/mcp_gateway/google_calendar_sync.py` | Remove or preserve only as deprecated migration aid | It simulates local-to-Google sync and is not provider-managed MCP. | If any user relies on local calendar cache, migration must document data handling. |
| `src/mcp_gateway/communication.py` | Split and replace with MCP wrappers | It contains email, WhatsApp, Telegram local implementations. Target providers own behavior. | Many tests and tool names depend on current functions. |
| `src/mcp_gateway/email_adapters.py` | Remove after Gmail MCP migration | SMTP/IMAP is not Gmail MCP and duplicates provider behavior. | Existing `.env.example` and local tests need rewrite. |

Recommended transition:

1. Add MCP provider registry and metadata.
2. Mark local adapters as legacy.
3. Route agent binding to provider-managed MCP entries only.
4. Keep API compatibility wrappers temporarily where needed.
5. Remove local implementations after tests and docs are migrated.

## 8. Tool Registry Design

### Unified Registry Concepts

The registry should distinguish:

- `implementation_type = local`
- `implementation_type = mcp`
- `implementation_type = removed`

It should not expose removed tools to the LLM. Removed tools may appear only in observability as blocked/deprecated entries during transition.

### Required Metadata

Each tool registration should include:

- `tool_id`
- `display_name`
- `provider`
- `category`
- `implementation_type`
- `enabled`
- `availability_status`
- `risk_class`
- `approval_policy`
- `read_write_capability`
- `external_side_effect`
- `destructive`
- `scheduled_capable`
- `provider_managed`
- `input_schema`
- `output_schema_hint`
- `observability_metadata`
- `last_discovered_at`
- `last_error`
- `replacement_tool_id` for removed/deprecated tools

### Example Tool IDs

- `local.personal_os.task.create`
- `local.personal_os.task.list`
- `local.cron.schedule.create`
- `mcp.search.tavily.search`
- `mcp.search.duckduckgo.search`
- `mcp.google_calendar.events.create`
- `mcp.gmail.messages.send`
- `mcp.whatsapp.messages.send`
- `mcp.telegram.messages.send`
- `removed.browser.safe_browse_url`
- `removed.code.run_code`

### Registry Outputs

The registry should provide:

- Agent-bindable tools: enabled and available only.
- Frontend catalog: enabled, unavailable, and removed status.
- Observability catalog: full metadata with redacted provider details.
- Policy catalog: approval/risk metadata.

## 9. Tool Routing Design

### Primary Agent Routing

Only the primary LLM may see user-facing tools. `node_agent()` should bind:

- enabled Personal OS tools.
- enabled cron-job tool actions.
- available provider-managed MCP tools.

It should not bind:

- browser sandbox.
- code sandbox.
- removed tools.
- unavailable provider tools.
- memory-worker-only internals.

### Personal OS Availability

Personal OS tools are available when:

- local DB is initialized.
- tool is enabled.
- policy metadata is loaded.
- required local resources are available.

### Cron-job Availability

cron-job tools are available when:

- scheduler schema is available.
- parser is available.
- scheduler policy is loaded.

Scheduler worker execution is explicit and must not auto-start accidentally.

### MCP Tool Availability

MCP tools are available when:

- provider config exists.
- provider discovery succeeds.
- tool schema is valid.
- local policy permits exposure.

Unavailable providers should not break chat. The agent should receive no bindable tool for that provider, and frontend status should explain the provider is unavailable.

### Removed Tool Blocking

If an old caller requests a removed tool:

- graph tool execution should return a blocked/removed message.
- API routes should be removed or return a deliberate deprecation response during transition.
- approval finalization should not execute removed tools.
- audit should record blocked removed-tool attempts.

### Approval-required Pause Behavior

High-risk tool calls should:

1. Create an approval request with preview.
2. Persist checkpoint/state as needed.
3. Return an approval-required response.
4. Execute only after approval.
5. Prevent duplicate execution.

### Tool Error Handling

Tool errors should be normalized:

- provider unavailable.
- validation error.
- policy denied.
- approval required.
- invocation failed retryable.
- invocation failed terminal.
- removed tool.

### Audit Logging

All invocations should write:

- tool call.
- tool result.
- audit event for write-capable, external, destructive, scheduled, approval-gated, failed, and blocked attempts.

### Secondary LLM Prevention

Secondary memory workers must not import or bind user-facing tool registries. Tests should scan and monkeypatch:

- `get_all_personal_os_tools`
- `get_all_mcp_tools`
- unified tool registry bind methods

Memory handlers may enqueue memory jobs only; they must not invoke Personal OS or MCP tools unless a future approved architecture explicitly adds a worker-safe tool lane.

### MCP Discovery Failure Fallback

If MCP discovery fails:

- do not fall back to local duplicate provider implementations.
- mark provider unavailable.
- expose safe error in observability.
- continue chat without that provider's tools.

## 10. HITL / Permission Policy Design

### Consolidated Policy Model

Replace split risk maps with one policy service. Inputs:

- tool metadata.
- normalized tool arguments.
- caller role.
- invocation source: chat, API, scheduler, approval resume.
- external side effect flag.
- destructive flag.
- provider-managed flag.
- scheduled run context.

Outputs:

- `no_approval_needed`
- `confirmation_recommended`
- `approval_required`
- `blocked`
- `provider_managed_confirmation`

### Policy Classification

| Tool/action | Policy |
|---|---|
| Web search | no approval needed |
| Calendar read | no approval needed |
| Calendar create | approval required |
| Calendar update | approval required |
| Calendar delete | approval required |
| Gmail read/search | no approval needed, confirmation recommended for broad/private queries |
| Gmail draft | confirmation recommended |
| Gmail send | approval required |
| WhatsApp read | no approval needed or confirmation recommended depending scope |
| WhatsApp send | approval required |
| Telegram read | no approval needed or confirmation recommended depending scope |
| Telegram send | approval required |
| Personal OS read | no approval needed |
| Personal OS low-risk write | confirmation recommended |
| Personal OS high-impact write | approval required |
| Cron create/update/delete | confirmation recommended for read-only actions, approval required for write/external/destructive actions |
| Cron-triggered read action | no approval needed if schedule was authorized |
| Cron-triggered write action | approval required unless durable preapproval exists |
| External communication | approval required |
| Destructive action | approval required or blocked |
| Removed tools | blocked |

### Provider-managed Confirmation

Some MCP providers may have their own confirmation or OAuth consent flows. Local HITL does not replace provider-managed confirmation. The local system should:

- present local approval first where required.
- invoke provider tool only after local approval.
- surface provider confirmation errors safely.
- never bypass provider-side permission checks.

## 11. Sandbox Removal Blueprint

### Deletion Order

1. Add baseline tests proving current references.
2. Add removed-tool metadata state.
3. Stop exposing sandbox tools to the agent registry.
4. Remove sandbox entries from `/api/tools`.
5. Remove or deprecate browser and GitHub/code API routes.
6. Remove integration status entries.
7. Update HITL policy to remove GitHub/code sandbox special cases or mark as blocked during transition.
8. Rewrite/delete sandbox tests.
9. Update docs and dependency files.
10. Delete sandbox source files.
11. Run static scans to prove no references remain.

### References to Clean

Imports:

- `src/mcp_gateway/registry.py`
- `src/api/server.py`
- tests importing `src.mcp_gateway.sandboxes.*`

Routes:

- `POST /api/browser/browse`
- `POST /api/browser/screenshot`
- `POST /api/github/clone`
- `POST /api/github/commit_and_push`
- `POST /api/github/merge`

Registry entries:

- `run_code`
- `github_clone`
- `github_commit_and_push`
- `github_merge`
- `safe_browse_url`
- `capture_screenshot`

HITL risk entries:

- Remove or block `github_merge` and `github_commit_and_push` if no replacement exists.
- Remove approval previews for GitHub sandbox actions unless a separate GitHub connector is later approved.
- Ensure `run_code` is blocked, not Low risk.

Frontend cleanup:

- Remove catalog/status visibility for browser/code sandbox.
- Update overview text.
- Show removed/deprecated entries only in observability if useful.

Tests to delete or rewrite:

- `tests/test_p4_browser.py`
- `tests/test_p4_github.py`
- sandbox sections in `tests/test_mcp_gateway.py`
- sandbox sections in `tests/test_real_tools.py`
- sandbox assertions in product/readiness tests
- code sandbox security tests after replacement blocked-tool tests exist

Docs/config/dependencies:

- Remove Playwright as Python backend dependency if no longer needed.
- Remove browser sandbox docs.
- Remove GitHub/code sandbox docs.

### Replacement Behavior for Old Callers

During migration:

- return `blocked_removed_tool` for old graph tool calls.
- return HTTP 410 or documented deprecation response for removed API routes if routes are temporarily kept.
- after final cleanup, routes should be removed and tests updated.

### Static Scan Commands

Run before deletion:

```powershell
rg -n "browser_sandbox|code_sandbox|safe_browse_url|capture_screenshot|run_code|github_clone|github_commit_and_push|github_merge|/api/browser|/api/github" src frontend tests docs README.md pyproject.toml requirements.txt
```

Run after deletion:

```powershell
rg -n "browser_sandbox|code_sandbox|safe_browse_url|capture_screenshot|run_code|github_clone|github_commit_and_push|github_merge|/api/browser|/api/github" src frontend tests docs README.md pyproject.toml requirements.txt
```

Expected final result:

- no runtime references.
- no active tests expecting sandbox behavior.
- no docs advertising sandbox behavior.
- no backend dependencies needed only by browser/code sandbox.

## 12. API Blueprint

### Preserve Existing Shapes Where Possible

Preserve until removal or explicit compatibility migration:

- `GET /api/tools`
- `GET /api/approvals`
- `POST /api/approvals/{request_id}/decision`
- `GET /api/scheduled`
- existing memory observability APIs

Removal may require deleting old browser/code API routes or returning explicit deprecation during transition.

### Final Tool Registry APIs

Recommended:

- `GET /api/tools`
  - returns unified catalog grouped by local, MCP, unavailable, and removed.
- `GET /api/tools/status`
  - registry health, provider counts, disabled tools, policy status.
- `GET /api/tools/{tool_id}`
  - detailed metadata with redacted config.

### MCP Provider Status APIs

Recommended:

- `GET /api/tools/mcp/providers`
- `GET /api/tools/mcp/providers/{provider_id}`
- `POST /api/tools/mcp/providers/{provider_id}/discover` if explicit admin refresh is allowed

The discover endpoint is not a provider behavior implementation. It only refreshes metadata from configured MCP servers.

### Personal OS APIs

Recommended:

- `GET /api/tools/personal-os/status`
- `GET /api/tools/personal-os/actions`
- `GET /api/tools/personal-os/audit`
- Keep `GET /api/tasks`, with migration to richer Personal OS task API when needed.

### Cron APIs

Recommended:

- `GET /api/tools/cron/schedules`
- `POST /api/tools/cron/schedules`
- `GET /api/tools/cron/schedules/{schedule_id}`
- `PATCH /api/tools/cron/schedules/{schedule_id}`
- `DELETE /api/tools/cron/schedules/{schedule_id}`
- `GET /api/tools/cron/runs`
- `POST /api/tools/cron/runs/{run_id}/retry` if explicit admin retry is approved

Keep `/api/scheduled` temporarily as compatibility wrapper if needed.

### Tool Call Audit APIs

Recommended:

- `GET /api/tools/observability/overview`
- `GET /api/tools/observability/calls`
- `GET /api/tools/observability/results`
- `GET /api/tools/observability/audit`
- `GET /api/tools/observability/blocked`

All observability APIs should be read-only and redacted by default.

## 13. Frontend Blueprint

### Existing Panels to Evolve

- `ToolsCockpit.jsx`
  - Show unified registry.
  - Separate local Personal OS, cron, MCP provider tools, unavailable providers, and removed tools.
  - Display risk class and approval policy.
- `ScheduledCockpit.jsx`
  - Replace simple `cron_or_timestamp` form with one-time/recurring scheduler form.
  - Show timezone, next run, last run, missed-run policy, status, approval state, and run history.
- `ApprovalInbox.jsx`
  - Preserve current behavior.
  - Add clearer previews for scheduled actions and provider-managed MCP writes.
- `OverviewCockpit.jsx`
  - Remove stale "22 OS + MCP Gateway" text.
  - Show provider-managed MCP readiness and removed sandbox status.

### New or Extended Panels

Tools Ops should include:

- Registry health.
- MCP provider status.
- Personal OS actions.
- Cron schedules and runs.
- Tool calls/results.
- Blocked removed-tool attempts.
- Approval policy matrix.

### Removed Tool Visibility

Browser/code sandbox should not appear as available tools. During transition, they may appear as removed/blocked only in operator observability.

### Provider Unavailable States

Frontend should clearly show:

- provider not configured.
- discovery failed.
- credentials missing.
- provider connected but tool unavailable.
- last error redacted.

## 14. Observability Blueprint

Read-only observability should cover:

- tool registry health.
- MCP availability.
- provider discovery state.
- tool invocation attempts.
- approvals.
- cron definitions and runs.
- Personal OS actions.
- failed tool calls.
- removed/blocked tools.

### Redaction

Redact:

- provider credentials.
- API keys.
- tokens.
- OAuth data.
- full email/message bodies.
- raw provider payloads unless explicitly allowed.
- hidden reasoning or scratchpad fields.

Preserve:

- tool IDs.
- provider IDs.
- status.
- timestamps.
- risk class.
- approval IDs.
- run IDs.
- redacted previews.

### Relationship to Memory Observability

Tools observability should mirror the safety posture of memory observability:

- additive.
- read-only by default.
- no hidden prompt/debug exposure.
- no mutation through status endpoints.

## 15. Testing Blueprint

### Registry Tests

- Personal OS and MCP registries are separate.
- Unified catalog includes implementation type.
- Removed tools are not agent-bindable.
- Risk metadata exists for every bindable tool.
- Provider-managed flag is true for MCP tools.

### Sandbox Removal Tests

- Browser/code tools absent from agent registry.
- Browser/code API routes removed or return deprecation during transition.
- No imports from `src.mcp_gateway.sandboxes`.
- Static scan has no forbidden references after deletion.

### Personal OS Tests

- Read tools execute without approval.
- Write tools use policy.
- Synthetic tools are absent or replaced.
- Personal OS does not call provider-managed MCP implementations directly.
- Personal OS uses memory retrieval/repositories only through approved boundaries.

### Cron Tests

- One-time schedules persist and execute once.
- Recurring schedules compute next run.
- Timezones are honored.
- Missed-run policy works.
- Retry and cancellation work.
- Scheduled high-risk action creates approval.
- Scheduler does not use `memory_jobs` as schedule definition table.

### MCP Tests

- Provider discovery succeeds with mocked MCP servers.
- Provider unavailable does not break chat.
- Tool schemas are normalized.
- Invocation goes through MCP client.
- No local duplicate provider functions are called.
- Search, Calendar, Gmail, WhatsApp, Telegram are provider-managed.

### Approval Policy Tests

- Calendar create/update/delete require approval.
- Gmail send requires approval.
- WhatsApp and Telegram send require approval.
- Cron-triggered writes require approval.
- Removed tools are blocked.
- Split risk maps are eliminated.

### Routing Tests

- Primary LLM sees only enabled available tools.
- Secondary LLM cannot bind or invoke user-facing tools.
- Provider discovery failure hides provider tools from binding.
- Removed tools cannot be resumed through old approval requests.

### Frontend Tests

- Tools catalog groups local/MCP/removed/unavailable.
- Scheduled panel shows next run/timezone/status.
- Provider status panels render unavailable state.
- Approval inbox handles tool approvals.
- Overview no longer advertises sandbox tools.

### API Compatibility Tests

- Existing retained endpoints keep response shape.
- Removed endpoints are intentionally removed or return documented deprecation.
- `/api/chat` shape unchanged.
- Memory observability unaffected.

## 16. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Accidental deletion of needed files | App import/startup failure | Reference cleanup and static scans before deletion |
| Premature sandbox deletion | Broken registry/API/tests | Disable exposure first, delete later |
| Broken MCP wiring | Missing provider tools | Mock MCP tests plus manual provider validation |
| Duplicate MCP implementations | Architectural drift and unsafe behavior | Static scans and provider-managed rule tests |
| Unsafe external writes without approval | User trust and safety failure | Consolidated policy and HITL tests |
| Cron job duplication | Repeated external actions | Idempotency keys and run claim locks |
| Timezone bugs | Missed/incorrect schedules | Store timezone and UTC, inject deterministic time in tests |
| Personal OS becomes too broad | Unmaintainable catch-all | Strict responsibilities and blocked actions |
| Frontend still references removed tools | User confusion and broken UI | Frontend smoke tests and catalog assertions |
| Tests mask provider-specific MCP failures | False confidence | Separate mocked protocol tests from manual provider validation |
| Provider credentials/config unknown | Migration blocked late | Manual validation phase before provider replacement |
| Approval resume executes removed tools | Unsafe legacy behavior | Removed-tool block in approval finalization |

## 17. Acceptance Criteria

The tools migration is complete when:

- Browser sandbox and code sandbox are fully removed from runtime, API, registry, frontend visibility, tests, docs, and dependencies.
- Personal OS is the only local non-MCP tool layer besides cron-job.
- Personal OS has explicit responsibilities, policy metadata, audit, idempotency, observability, and memory-aware boundaries.
- cron-job supports durable one-time and recurring schedules with timezone, next/last run, missed-run policy, run attempts, approval, and observability.
- Tavily/DuckDuckGo, Google Calendar, WhatsApp, Telegram, and Gmail tools are provider-managed MCP tools.
- Local code no longer reimplements provider behavior for target MCP providers.
- Unified registry metadata distinguishes local, MCP, and removed tools.
- Primary LLM can route available tools correctly.
- Secondary memory LLM cannot call user-facing tools.
- HITL policy is centralized and consistent across graph, API, scheduler, and MCP invocation.
- Tool observability is read-only and redacted.
- Existing retained API response shapes are preserved.
- Frontend no longer advertises removed tools and shows provider availability clearly.
- Tests cover registry, routing, policy, cron, MCP discovery, sandbox removal, frontend, and API compatibility.
- Manual validation for target MCP provider configs is documented and complete.

## 18. Implementation Strategy

This is a safe sequence of phases, not the final detailed roadmap.

### Phase 0: Baseline Audit and Safety Tests

- Capture current tool registry/API behavior.
- Add static scan tests for sandbox references.
- Add baseline tests proving no secondary LLM tool binding.
- Document current MCP provider config unknowns.

### Phase 1: Registry Separation

- Split local Personal OS, cron, provider-managed MCP, and removed-tool metadata.
- Do not delete sandboxes yet.
- Ensure removed tools can be represented as blocked but not agent-bindable.

### Phase 2: Sandbox Removal Preparation

- Remove browser/code sandbox exposure from agent binding and `/api/tools`.
- Add blocked/deprecated behavior for old callers.
- Update HITL finalization so removed tools cannot execute.

### Phase 3: Sandbox Deletion

- Remove sandbox routes, imports, tests, docs, and dependencies.
- Delete browser/code sandbox files only after scans pass.

### Phase 4: Personal OS Redesign

- Introduce bounded Personal OS tool metadata, repositories, policy, audit, and observability.
- Replace/remove synthetic tools.
- Integrate with memory retrieval and procedural skills through approved boundaries.

### Phase 5: Cron-job Fix

- Introduce scheduler definitions and run attempts.
- Add cron parser, timezone, next/last run, missed-run policy, retries, cancellation, approval, and observability.
- Keep scheduler separate from memory_jobs.

### Phase 6: MCP Provider Wiring

- Validate provider configs manually.
- Discover and register Tavily/DuckDuckGo, Google Calendar, WhatsApp, Telegram, and Gmail MCP tools.
- Replace local provider adapters with thin MCP boundaries or remove them.

### Phase 7: Tool Routing and HITL Policy

- Centralize permission policy.
- Enforce primary-only tool binding.
- Ensure provider unavailable behavior is safe.
- Ensure approval pause/resume handles MCP and cron contexts.

### Phase 8: Observability and Frontend

- Add Tools Ops observability.
- Update Tools Catalog, Scheduled Jobs, Approval Inbox, and Overview panels.
- Show provider status and removed-tool state safely.

### Phase 9: Docs and E2E Hardening

- Update README, architecture docs, env templates, and runbooks.
- Add E2E tests for chat tool routing, MCP unavailable behavior, cron execution, approvals, observability, and frontend smoke.
- Run final static scans proving no sandbox/local duplicate provider behavior remains.

