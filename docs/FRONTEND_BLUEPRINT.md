# Frontend Integration Blueprint

## 1. Executive Summary

This blueprint maps the existing Ivo frontend in `frontend/src` to the backend APIs implemented in `src/api/server.py`. It is intentionally limited to integration work: no visual redesign, no new endpoints, no backend API changes, no dependency changes, and no speculative features.

The frontend already has working panels for chat, sessions, loop events, memory browsing, memory observability, approvals, tool catalog, tools observability, cron schedules, data inspection, and task/sub-agent listing. The main gaps are incomplete coverage of existing backend APIs, partial handling of approval/provider-unavailable states, and disconnected direct provider wrappers for search, calendar, email, skills, backups, and integration status. The safest next implementation step is to refine existing components and API adapters around the current response shapes rather than redesigning the UI.

Primary source files inspected:

- Backend routes: `src/api/server.py`
- Memory observability helpers: `src/memory/observability.py`
- Tools observability helpers: `src/tools/observability.py`
- MCP provider registry: `src/tools/mcp_provider_registry.py`
- MCP gateway registry: `src/mcp_gateway/registry.py`
- Personal OS observability: `src/personal_os/observability.py`
- Scheduler service/store: `src/personal_os/scheduler_service.py`, `src/personal_os/scheduler_store.py`
- Frontend shell and components: `frontend/src/App.jsx`, `frontend/src/components/*.jsx`

## 2. Existing Backend API Inventory

Status meanings: `integrated` means the frontend calls and consumes the endpoint; `partial` means the endpoint is called but important fields/states are missed; `missing` means no frontend caller was found; `broken` means an observed caller appears incompatible with current endpoint behavior.

| Method | Endpoint | Purpose | Request / response shape | Source | Frontend usage |
|---|---|---|---|---|---|
| GET | `/api/health` | Basic backend health and heartbeat. | Response: `{status, heartbeat, backend}`. | `src/api/server.py:162` | missing |
| GET | `/api/sessions` | List chat sessions from `raw_turns`. | Response: `{sessions: string[]}`. | `src/api/server.py:174` | integrated by `frontend/src/components/ChatCockpit.jsx:22` |
| GET | `/api/history/{session_id}` | Session turns and loop trace. | Response: `{session_id, turns, total_turns, loop_events, loop_trace}`. | `src/api/server.py:183` | integrated by Chat, Loop, Overview |
| GET | `/api/loop/events/{session_id}` | Alias for history/loop trace. | Same as history response. | `src/api/server.py:184` | partial fallback in `LoopCockpit.jsx:15` |
| GET | `/api/loop/events` | Default-session loop trace. | Same as history response with default session. | `src/api/server.py:185` | missing |
| PUT | `/api/history/{session_id}` | Rename session across raw turns, loop events, approvals. | Request `{new_session_id}`; response `{status, old_session_id, new_session_id}`. | `src/api/server.py:215` | integrated by `ChatCockpit.jsx:175` |
| DELETE | `/api/history/{session_id}` | Delete session turns/events/approvals. | Response `{status, message}`. | `src/api/server.py:229` | integrated by `ChatCockpit.jsx:199` |
| GET | `/api/models` | Primary/secondary model catalog and memory defaults. | Response `{catalog, memory_defaults}`. | `src/api/server.py:240` | partial: Chat uses `catalog`, ignores `memory_defaults` |
| POST | `/api/chat` | Run graph chat turn. | Request `{message, session_id, provider, model_name, secondary_provider, secondary_model_name}`; response `{session_id, session_title, response, retrieval_triggered, retrieved_memories, pending_approval_id, approval_status, iterations, tools_used, loop_events, loop_trace}`. | `src/api/server.py:248` | partial: Chat uses response and loop trace, but does not surface retrieval metadata or approval pending clearly |
| GET | `/api/memory` | Permanent semantic facts only. | Response `{facts, total_facts}`. | `src/api/server.py:348` | missing; Memory panel uses `/api/memory/full` |
| POST | `/api/memory/fact` | Explicit permanent fact write. | Request `{category, fact_text}`; response `{status, message}`. | `src/api/server.py:353` | missing |
| GET | `/api/memory/full` | Legacy full memory view. | Query `query?`; response `{facts, episodes, soul_md, skill_md, memory_md}`. | `src/api/server.py:360` | integrated by `MemoryCockpit.jsx:14` |
| GET | `/api/memory/observability/health` | Memory system health. | Query `stale_after_seconds?`; response includes `{status, schema, queue, workers, semantic, procedural, skills}`. | `src/api/server.py:380`, `src/memory/observability.py` | integrated by Memory Ops |
| GET | `/api/memory/observability/jobs` | Memory job queue list/summary. | Query `session_id,status,job_type,limit,include_payload`; response `{summary, jobs}`. | `src/api/server.py:384` | partial: Memory Ops fetches default only, no filters/payload toggle |
| GET | `/api/memory/observability/workers` | Worker heartbeat/staleness. | Query `stale_after_seconds,include_host_metadata`; response `{summary, workers}`. | `src/api/server.py:400` | partial: default only |
| GET | `/api/memory/observability/dead-letter` | Dead-lettered memory jobs. | Query `limit,include_details`; response `{summary, dead_letters}`. | `src/api/server.py:410` | partial: default only, no details toggle |
| POST | `/api/memory/observability/retrieval/trace` | Read-only retrieval trace. | Request `{query, session_id, provider, model_name, include_candidates, include_prompt_block, max_candidates}`; response `{query, session_id, gate, plan, retrieval, assembly, candidates}`. | `src/api/server.py:414`, `src/memory/observability.py` | integrated by Memory Ops; handles prompt-block toggle |
| GET | `/api/memory/observability/semantic` | Semantic candidate/dedup/consolidation observability. | Query `session_id,status,limit`; response includes `summary`, `candidates`, dedup/consolidation rows. | `src/api/server.py:431` | partial: default only, no filters |
| GET | `/api/memory/observability/procedural` | Procedural candidate/approval observability. | Query `status,limit`; response includes `summary`, `candidates`, `approvals`. | `src/api/server.py:439` | partial: default only |
| GET | `/api/memory/observability/skills` | Skill version/usage observability. | Query `include_archived`; response includes `summary`, active/archived/usage rows. | `src/api/server.py:443` | partial: active versions shown only |
| GET | `/api/memory/observability/overview` | Combined memory observability. | Response combines health/jobs/workers/dead-letter/semantic/procedural/skills. | `src/api/server.py:447` | integrated by Memory Ops |
| GET | `/api/skills` | Legacy-compatible active procedural skills. | Response `{skills, total_skills}`. | `src/api/server.py:453` | missing |
| POST | `/api/skills` | Create versioned skill through compatibility path. | Request `{name, description, trigger_keywords, execution_steps}`; response `{status, message}`. | `src/api/server.py:458` | missing |
| DELETE | `/api/skills/{skill_name}` | Disable/archive active skill. | Response `{status, message}`. | `src/api/server.py:470` | missing |
| GET | `/api/calendar/events` | Calendar availability/read wrapper. | Query `start_date,end_date`; response `{events: [], total_events: 0, result}`. | `src/api/server.py:485` | missing |
| POST | `/api/calendar/events` | Calendar create request requiring approval. | Request `{title,start_time,end_time,attendees,location,status}`; response `{status: APPROVAL_REQUIRED, approval_request, message}`. | `src/api/server.py:493` | missing |
| PUT | `/api/calendar/events/{event_id}` | Calendar update wrapper. | Request calendar event fields; response `{status, result}`. | `src/api/server.py:514` | missing; Needs verification because update appears direct while create/delete require approval |
| DELETE | `/api/calendar/events/{event_id}` | Calendar delete approval request. | Response `{status: APPROVAL_REQUIRED, approval_request, message}`. | `src/api/server.py:527` | missing |
| GET | `/api/email/messages` | Gmail read/search wrapper. | Query `limit,query`; response `{messages: [], total_messages: 0, result}`. | `src/api/server.py:548` | missing |
| POST | `/api/email/draft` | Gmail draft wrapper. | Request `{to, subject, body}`; response `{status, result}`. | `src/api/server.py:556` | missing |
| POST | `/api/email/send` | Gmail send approval request. | Request `{to, subject, body}`; response `{status: APPROVAL_REQUIRED, approval_request, message}`. | `src/api/server.py:561` | missing |
| GET | `/api/search` | Search MCP wrapper. | Query `q,max_results`; response `{query, results, total_results}`. | `src/api/server.py:578` | missing |
| GET | `/api/tools` | Legacy tool catalog. | Response `{total_tools, personal_os_tools, mcp_tools}`. | `src/api/server.py:593` | integrated by Tools Catalog, but mostly uses observability groups |
| GET | `/api/tools/status` | Tools status summary. | Response `{status, registry, providers, policy, removed_tools}`. | `src/api/server.py:604`, `src/tools/observability.py` | missing; Tools panels use overview instead |
| GET | `/api/tools/observability/overview` | Combined tools observability. | Response `{status, registry, providers, policy, cron, tool_calls, tool_results, audit, blocked}`. | `src/api/server.py:611` | integrated by Tools Catalog and Tools Ops |
| GET | `/api/tools/observability/calls` | Tool call audit list. | Query `limit`; response `{tool_calls,total_returned,counts}`. | `src/api/server.py:618` | missing as standalone; included via overview |
| GET | `/api/tools/observability/results` | Tool result audit list. | Query `limit`; response `{tool_results,total_returned,counts}`. | `src/api/server.py:625` | missing as standalone; included via overview |
| GET | `/api/tools/observability/audit` | Tool audit log list. | Query `limit`; response `{audit_events,total_returned,counts}`. | `src/api/server.py:632` | missing as standalone; Personal OS audit has separate caller |
| GET | `/api/tools/observability/blocked` | Blocked attempts. | Query `limit`; response `{blocked_attempts,total_returned,removed_tool_names}`. | `src/api/server.py:639` | missing as standalone; included via overview |
| GET | `/api/tools/mcp/providers` | Target MCP provider statuses. | Response `{providers}` with provider status/tools redacted. | `src/api/server.py:645` | integrated by Tools Ops |
| GET | `/api/tools/mcp/providers/{provider_id}` | One MCP provider status. | Response provider status or 404. | `src/api/server.py:652` | missing |
| POST | `/api/tools/mcp/providers/{provider_id}/discover` | Explicit safe metadata discovery refresh. | Response provider status or 404. | `src/api/server.py:662` | missing |
| GET | `/api/tools/personal-os/status` | Personal OS bounded status. | Response responsibilities/non-responsibilities and table counts. | `src/api/server.py:672`, `src/personal_os/observability.py` | integrated by Tools Ops |
| GET | `/api/tools/personal-os/actions` | Personal OS action metadata/policy. | Response `{actions}`. | `src/api/server.py:679` | integrated by Tools Ops |
| GET | `/api/tools/personal-os/audit` | Personal OS audit events. | Query `limit`; response `{audit_events,total_events}`. | `src/api/server.py:686` | integrated by Tools Ops |
| GET | `/api/tasks` | Local task/sub-agent board. | Response `{tasks,total_tasks,tasks_summary,sub_agents}`. | `src/api/server.py:694` | integrated by TaskBoard |
| GET | `/api/tools/cron/schedules` | List durable cron schedules. | Query `status,limit`; response `{schedules}`. | `src/api/server.py:724` | integrated by Scheduled and Tools Ops; filters missing |
| POST | `/api/tools/cron/schedules` | Create one-time/recurring schedule. | Request `{schedule_type,target_tool_id,target_payload,cron_expression,run_at,timezone,missed_run_policy,max_catchup_runs,created_by}`; response `{status, schedule, legacy_mirrored}`. | `src/api/server.py:731` | integrated by ScheduledCockpit |
| GET | `/api/tools/cron/schedules/{schedule_id}` | Get one schedule. | Response `{schedule}`. | `src/api/server.py:752` | missing |
| PATCH | `/api/tools/cron/schedules/{schedule_id}` | Update schedule safely. | Request patch fields; response `{status,schedule}` or 403 if risk increases. | `src/api/server.py:763` | missing |
| DELETE | `/api/tools/cron/schedules/{schedule_id}` | Cancel schedule. | Response `{status,schedule}`. | `src/api/server.py:788` | integrated by ScheduledCockpit |
| GET | `/api/tools/cron/runs` | List schedule run attempts. | Query `schedule_id,status,limit`; response `{runs}`. | `src/api/server.py:799` | integrated by Scheduled/Tools Ops; filters missing |
| GET | `/api/scheduled` | Legacy scheduled jobs table. | Response `{scheduled_jobs}`. | `src/api/server.py:806` | missing; acceptable if deprecated compatibility only |
| POST | `/api/scheduled` | Legacy schedule create wrapper. | Request `{cron_or_timestamp,task_payload}`; response `{status,message}`. | `src/api/server.py:816` | missing; keep as compatibility, not primary UI |
| DELETE | `/api/scheduled/{job_id}` | Legacy schedule cancel wrapper. | Response `{status,message}`. | `src/api/server.py:825` | missing; keep as compatibility, not primary UI |
| GET | `/api/system/backups` | List available backups. | Response `{backups,total_backups}`. | `src/api/server.py:833` | missing |
| GET | `/api/system/health` | System telemetry. | Response `{status,app_name,database_path,schema_version,worker_status,providers}`. | `src/api/server.py:840` | partial: Overview uses schema/provider booleans; worker status may be misleading because server returns `RUNNING` unconditionally |
| GET | `/api/data/tables` | List inspectable DB tables. | Response `{tables}`. | `src/api/server.py:859` | integrated by DataCockpit |
| GET | `/api/data/table/{table_name}` | Inspect rows. | Query `limit`; response `{table,total_rows,columns,rows}`. | `src/api/server.py:869` | partial: DataCockpit ignores `columns`, `total_rows`, and `limit` |
| GET | `/api/approvals` | List approval requests. | Response `{approval_requests}`. | `src/api/server.py:893` | integrated by ApprovalInbox |
| POST | `/api/approvals/{request_id}/decision` | Approve/reject request; procedural approval has enriched result. | Request `{decision}`; response either graph resume result or procedural skill approval result. | `src/api/server.py:898` | partial: ApprovalInbox handles generic status/tool only, not procedural details/unavailable results |
| POST | `/api/system/backup` | Create system backup. | Response from `export_agent_backup()`. | `src/api/server.py:935` | missing |
| POST | `/api/system/restore` | Restore from backup path. | Request `{backup_path}`; response restore result or 400. | `src/api/server.py:940` | missing |
| GET | `/api/integrations/status` | MCP integration capability/status compatibility endpoint. | Response `{integrations:{calendar,email_smtp,email_imap,whatsapp,telegram,search}}`. | `src/api/server.py:952` | missing |

`GET /` is also mounted for static frontend serving at `src/api/server.py:998`, but it is not counted as an API endpoint in this blueprint.

## 3. Existing Frontend Structure

Application shell:

- `frontend/src/App.jsx` owns tab state and current session state. It wires tabs for Overview, Chat, Loop Timeline, Task & Sub-Agents, Memory, Memory Ops, Approvals, Tools Catalog, Tools Ops, Scheduled Jobs, Data Inspector.

Current components and API calls:

- `ChatCockpit.jsx`: calls `/api/sessions`, `/api/models`, `/api/history/{session_id}`, `/api/chat`, `PUT /api/history/{session_id}`, `DELETE /api/history/{session_id}`. Keeps local message state, session list, model selectors, loading/error/toast states.
- `LoopCockpit.jsx`: calls `/api/history/{session_id}`, falls back to `/api/loop/events/{session_id}`. Displays loop events.
- `OverviewCockpit.jsx`: calls `/api/history/{session_id}` and `/api/system/health`. Displays telemetry derived partly in frontend.
- `MemoryCockpit.jsx`: calls `/api/memory/full` with optional `query`. Displays facts, episodes, SOUL.md, SKILL.md, MEMORY.md.
- `MemoryObservabilityCockpit.jsx`: calls all memory observability endpoints and posts retrieval trace. Has loading/error/empty states and prompt-block toggle.
- `ApprovalInbox.jsx`: calls `/api/approvals` and `POST /api/approvals/{request_id}/decision`. Displays pending approvals and action status.
- `ToolsCockpit.jsx`: calls `/api/tools` and `/api/tools/observability/overview`. Uses registry groups from observability more than legacy catalog.
- `ToolsOpsCockpit.jsx`: calls `/api/tools/observability/overview`, `/api/tools/mcp/providers`, `/api/tools/personal-os/status`, `/api/tools/personal-os/actions`, `/api/tools/personal-os/audit`, `/api/tools/cron/schedules`, `/api/tools/cron/runs?limit=20`.
- `ScheduledCockpit.jsx`: calls `/api/tools/cron/schedules`, `/api/tools/cron/runs?limit=20`, `POST /api/tools/cron/schedules`, and `DELETE /api/tools/cron/schedules/{id}`.
- `TaskBoard.jsx`: calls `/api/tasks`.
- `DataCockpit.jsx`: calls `/api/data/tables` and `/api/data/table/{table_name}`.

Reusable pieces worth keeping:

- Chat/session state flow in `ChatCockpit.jsx`.
- Read-only table helper pattern in `MemoryObservabilityCockpit.jsx`.
- Badge/status patterns in `ToolsCockpit.jsx` and `ToolsOpsCockpit.jsx`.
- Explicit retrieval trace request flow in `MemoryObservabilityCockpit.jsx`.
- Cron schedule create/cancel and run-list wiring in `ScheduledCockpit.jsx`.
- Data inspector table switching in `DataCockpit.jsx`.

## 4. Backend Frontend Integration Map

| Backend area | Existing backend source | Frontend component | Current status | Notes |
|---|---|---|---|---|
| Chat and sessions | `src/api/server.py:174-348` | `ChatCockpit.jsx`, `LoopCockpit.jsx`, `OverviewCockpit.jsx` | partial | Core chat/session flow works; retrieval/approval metadata from `/api/chat` is underused. |
| Model catalog | `src/api/server.py:240` | `ChatCockpit.jsx` | partial | Uses `catalog.providers`; ignores `memory_defaults`. |
| Memory browsing | `src/api/server.py:348-370` | `MemoryCockpit.jsx` | partial | Uses `/api/memory/full`; no explicit fact write UI and no `/api/memory` lightweight view. |
| Memory observability | `src/api/server.py:380-447`, `src/memory/observability.py` | `MemoryObservabilityCockpit.jsx` | integrated/partial | Endpoints wired; filters/details mostly not exposed. |
| Skills compatibility API | `src/api/server.py:453-470` | none | missing | Skill CRUD exists but frontend only sees skill versions through memory/tools ops. |
| Calendar wrappers | `src/api/server.py:485-527` | none | missing | Approval-required create/delete not exposed. Update path needs policy verification. |
| Email wrappers | `src/api/server.py:548-561` | none | missing | Read/draft/send wrappers not exposed; send requires approval. |
| Search wrapper | `src/api/server.py:578` | none | missing | Provider-unavailable state should be handled if exposed. |
| Tools catalog/status | `src/api/server.py:593-604` | `ToolsCockpit.jsx`, `ToolsOpsCockpit.jsx` | partial | `/api/tools` and overview used; `/api/tools/status` unused. |
| Tool observability | `src/api/server.py:611-639`, `src/tools/observability.py` | `ToolsCockpit.jsx`, `ToolsOpsCockpit.jsx` | partial | Overview used; standalone calls/results/audit/blocked endpoints unused. |
| MCP provider status | `src/api/server.py:645-662`, `src/tools/mcp_provider_registry.py` | `ToolsOpsCockpit.jsx` | partial | Provider list shown; detail and discovery endpoints unused. |
| Personal OS observability | `src/api/server.py:672-686`, `src/personal_os/observability.py` | `ToolsOpsCockpit.jsx` | integrated | Status/actions/audit are fetched. |
| Tasks/sub-agents | `src/api/server.py:694-721` | `TaskBoard.jsx` | integrated | Read-only board is wired. |
| Cron scheduler | `src/api/server.py:724-825`, `src/personal_os/scheduler_service.py` | `ScheduledCockpit.jsx`, `ToolsOpsCockpit.jsx` | partial | List/create/delete and runs are wired; get-one, patch, filters, approval status details are not. |
| System backup/restore | `src/api/server.py:833-840`, `src/api/server.py:935-949` | none | missing | Backup list/create/restore not exposed. Restore is a write/destructive admin action. |
| Data inspector | `src/api/server.py:859-885` | `DataCockpit.jsx` | partial | Table list/rows wired; limit/columns/total rows are underused. |
| Approvals/HITL | `src/api/server.py:893-923` | `ApprovalInbox.jsx` | partial | Basic approve/reject works; procedural approval payload and fail-closed/unavailable statuses need clearer handling. |
| Integration status | `src/api/server.py:952-985` | none | missing | Could support disconnected provider summaries without inventing new backend. |
## 5. Missing or Partial Frontend API Wiring

Missing frontend callers for existing APIs:

- `/api/health`: no direct lightweight backend health check. Current Overview uses `/api/system/health` instead.
- `/api/memory`: no lightweight facts-only view.
- `POST /api/memory/fact`: no explicit permanent fact entry path.
- `/api/skills`, `POST /api/skills`, `DELETE /api/skills/{skill_name}`: no skill compatibility management panel.
- Calendar wrappers: `/api/calendar/events` GET/POST/PUT/DELETE are not called.
- Email wrappers: `/api/email/messages`, `/api/email/draft`, `/api/email/send` are not called.
- `/api/search`: not called.
- `/api/tools/status`: not called.
- Standalone tool observability endpoints: `/api/tools/observability/calls`, `/results`, `/audit`, `/blocked` are not called directly.
- MCP provider detail and discovery: `/api/tools/mcp/providers/{provider_id}`, `POST /api/tools/mcp/providers/{provider_id}/discover` are not called.
- Cron schedule detail/update/filtering: `GET/PATCH /api/tools/cron/schedules/{schedule_id}`, filters on schedules/runs are not used.
- Legacy `/api/scheduled` endpoints are not called; this is probably acceptable because `ScheduledCockpit.jsx` uses the durable cron APIs.
- Backup/restore APIs are not called.
- `/api/integrations/status` is not called.

Partial wiring:

- `ChatCockpit.jsx` receives `retrieval_triggered`, `retrieved_memories`, `pending_approval_id`, and `approval_status` from `/api/chat`, but only displays response and loop tool events.
- `ApprovalInbox.jsx` assumes all approvals are high-risk requests and does not distinguish provider unavailable, removed/blocked, procedural skill promotion, cron-triggered approval, or approval resume failure result shapes.
- `MemoryObservabilityCockpit.jsx` fetches memory jobs/workers/dead letters/semantic/procedural data but does not expose existing query filters such as status, job type, session, include payload/details, archived skills, or row limits.
- `ToolsOpsCockpit.jsx` uses `/api/tools/observability/overview` and provider list, but does not use `/api/tools/status` or standalone drill-down endpoints. It also does not trigger safe provider discovery refresh.
- `ScheduledCockpit.jsx` creates and cancels schedules but does not use existing patch/update, get-one, status filters, or run filters.
- `DataCockpit.jsx` ignores `columns`, `total_rows`, and `limit` from `/api/data/table/{table_name}`.

## 6. Broken or Outdated Frontend Integrations

No hard-broken fetch paths were found in `frontend/src`; there are no current calls to removed `/api/browser` or `/api/github` routes.

Integration risks and outdated assumptions:

- `OverviewCockpit.jsx` displays `worker_status` from `/api/system/health`, but `src/api/server.py:840` returns `worker_status: "RUNNING"` statically. Memory worker reality is better represented by `/api/memory/observability/workers` and `/api/memory/observability/health`. Treat current Overview worker status as potentially misleading.
- `OverviewCockpit.jsx` uses `/api/system/health.providers`, which comes from `validate_integration_environment()` rather than the newer MCP provider status registry. For final MCP status, `/api/tools/mcp/providers` and `/api/integrations/status` are more directly aligned with the tools architecture.
- `ApprovalInbox.jsx` labels approvals with one risk treatment; current approvals can include procedural skill promotion, cron-triggered action approval, provider-managed external writes, removed-tool fail-closed results, and unavailable-provider results.
- `ChatCockpit.jsx` does not make approval-pending actionable even though `/api/chat` returns `pending_approval_id` and `approval_status`.
- `MemoryCockpit.jsx` still presents `/api/memory/full` legacy content only; newer pipeline states are in Memory Ops and Data Inspector, not in the basic Memory panel.
- `ScheduledCockpit.jsx` allows free-form `target_tool_id` and payload JSON. The backend validates policy/schedule semantics, but the frontend does not currently use `/api/tools/observability/overview` or `/api/tools/status` to identify unavailable or approval-required targets before submission.
- `GET /api/calendar/events`, `GET /api/email/messages`, and `GET /api/search` return compatibility wrappers where provider availability may be unavailable; because there is no frontend caller, disconnected states are currently visible only through Tools Ops/MCP provider status.

## 7. Backend Features Not Yet Exposed in Frontend

Existing backend features with no direct frontend access:

- Explicit semantic fact write via `POST /api/memory/fact`.
- Procedural skill compatibility CRUD via `/api/skills`.
- Calendar availability/create/update/delete wrappers.
- Email read/search/draft/send wrappers.
- Search wrapper.
- MCP provider detail endpoint and explicit discovery refresh endpoint.
- Tool status summary endpoint.
- Standalone tool calls/results/audit/blocked lists.
- Cron schedule detail and patch/update endpoint.
- Cron list filters by status and run filters by schedule/status.
- Backup list/create/restore endpoints.
- Integration compatibility status endpoint.
- Lightweight `/api/health` endpoint.
- Memory observability filters and detail toggles.

Expose only where the backend already supports it and only with existing approval/provider-unavailable semantics.

## 8. Required UI States From Existing APIs

The frontend already has basic loading, empty, and error states in most panels. The following states are required by current backend responses and should be handled explicitly during integration refinement.

| State | Backend source | Existing frontend handling | Gap |
|---|---|---|---|
| loading | All fetch calls | Present in Chat, Loop, Memory, Memory Ops, Tools, Tools Ops, Scheduled, Data, TaskBoard, Approvals | Keep existing loading states; avoid global blocking where one panel has partial failure. |
| empty | List endpoints returning empty arrays | Present in most list panels | DataCockpit treats empty selected table as table-empty; should also handle no tables. |
| error | Non-2xx or fetch failure | Present in most panels | Many errors show only HTTP status; backend `detail` should be surfaced where present. |
| disconnected provider | `/api/tools/mcp/providers`, `/api/integrations/status`, tool wrapper results | Tools Ops shows provider status | Direct search/calendar/email panels do not exist; Overview uses older provider booleans. |
| approval required | Calendar create/delete, email send, cron high-risk schedule/run, chat tool calls | ApprovalInbox lists requests; Scheduled can create schedules | Chat and direct provider wrappers do not surface approval request IDs inline. |
| approval pending | `/api/chat` returns `pending_approval_id`, `approval_status`; `/api/approvals` lists requests | ApprovalInbox handles list | Chat does not link pending chat turn to ApprovalInbox/request ID. |
| tool unavailable | Tools policy/invocation and MCP provider unavailable responses | Tools Ops shows unavailable providers/tools | Direct provider wrapper endpoints have no UI and no unavailable result handling. |
| scheduled run pending/failed | `/api/tools/cron/runs` statuses | ScheduledCockpit lists recent runs | No filters or detail view for failed/pending runs. |
| dead-lettered memory job | `/api/memory/observability/dead-letter` | Memory Ops lists defaults | No details toggle/filter. |
| stale worker | `/api/memory/observability/workers` | Memory Ops displays default worker table | Overview worker status can contradict this. |
| procedural approval promotion result | `/api/approvals/{id}/decision` may return `procedural_skill_approval` | Not differentiated | ApprovalInbox should preserve generic flow while showing available procedural result fields. |

## 9. External/MCP Integration States

Only states supported by current code are included here.

| Provider | Backend support | Frontend support | States to handle |
|---|---|---|---|
| Gmail | Provider IDs/status in `src/tools/mcp_provider_registry.py`; wrappers `/api/email/messages`, `/api/email/draft`, `/api/email/send`; metadata in `src/mcp_gateway/registry.py`. | Tools Ops provider list only. No email panel. | `available`, `unavailable/not_configured`, `discovery_failed`, `tool_count`, approval required for send, safe unavailable wrapper result. |
| Google Calendar | Provider status plus `/api/calendar/events` GET/POST/PUT/DELETE wrappers. | Tools Ops provider list only. No calendar panel. | Read availability, create/delete approval required, provider unavailable, update policy needs verification. |
| WhatsApp | Provider status and metadata for `whatsapp_read`, `whatsapp_send` in MCP gateway registry. No REST API routes found in `src/api/server.py`. | Tools Ops provider list only. | Available/unavailable/discovery failed, send approval required through tool policy. No direct frontend action endpoint found. |
| Telegram | Provider status and metadata for `telegram_read`, `telegram_send` in MCP gateway registry. No REST API routes found in `src/api/server.py`. | Tools Ops provider list only. | Available/unavailable/discovery failed, send approval required through tool policy. No direct frontend action endpoint found. |
| Tavily/DuckDuckGo Search | Provider IDs `search_tavily`, `search_duckduckgo`; `/api/search?q=&max_results=` wrapper. | Tools Ops provider list only. No search panel. | Available if either provider is available, unavailable/not_configured, discovery failed, empty results, query validation error. |

Needs verification:

- Real MCP provider configs and transports are not validated by this blueprint. Current provider status may show unavailable until `.agent/mcp_config.json` and provider credentials are configured outside the frontend.
- Calendar update route currently invokes `calendar_update_event` directly in `src/api/server.py:514`, while create/delete explicitly create approval requests. Verify whether this is intentional before adding frontend update controls.
- Email draft route invokes directly and send creates approval. Verify provider capability availability before adding draft/send flows.
## 10. Recommended Frontend Fix Order

1. Preserve working integrations first.
   - Keep current `ChatCockpit`, `MemoryObservabilityCockpit`, `ToolsOpsCockpit`, `ScheduledCockpit`, `ApprovalInbox`, `DataCockpit`, and `TaskBoard` endpoint wiring.
   - Do not rename or reshape backend responses.

2. Introduce a small frontend API adapter layer around existing endpoints.
   - Centralize fetch/error parsing for `detail` responses.
   - Keep endpoint paths unchanged.
   - This reduces repeated HTTP status handling in each component.

3. Fix approval-state handling across existing components.
   - In `ChatCockpit.jsx`, use existing `/api/chat` fields `pending_approval_id` and `approval_status` to show that the assistant is paused for approval.
   - In `ApprovalInbox.jsx`, handle generic graph resume responses, procedural skill approval responses, unavailable-provider results, blocked removed-tool results, and rejected decisions without assuming every request has the same risk/result type.

4. Align system/provider status with current tools architecture.
   - Keep `OverviewCockpit.jsx` working, but source provider status from existing `/api/tools/mcp/providers` or `/api/integrations/status` where appropriate.
   - Treat `/api/system/health.worker_status` as coarse system telemetry and memory worker state as `/api/memory/observability/workers`.

5. Refine Tools Ops using existing drill-down endpoints.
   - Add calls to `/api/tools/status`, `/api/tools/observability/calls`, `/results`, `/audit`, and `/blocked` when the panel needs independent refresh/filtering.
   - Use existing `/api/tools/mcp/providers/{provider_id}` and optional `POST /discover` only as explicit metadata refresh, never as provider action execution.

6. Refine cron wiring without changing scheduler semantics.
   - Use `GET /api/tools/cron/schedules/{schedule_id}` for detail inspection.
   - Use `PATCH /api/tools/cron/schedules/{schedule_id}` for existing update capability.
   - Use existing `status`, `schedule_id`, and `limit` filters for schedule/run lists.
   - Surface `WAITING_FOR_APPROVAL`, `FAILED_RETRYABLE`, `FAILED_TERMINAL`, and `CANCELLED` from existing run statuses.

7. Expose memory and skill write paths only where backend already supports them.
   - `POST /api/memory/fact` can be wired as an explicit permanent fact write path.
   - `/api/skills` can be wired for legacy-compatible active skill management, while Memory Ops remains the observability surface for versioned skills and procedural candidates.

8. Add provider wrapper panels only if needed, using existing endpoints.
   - Search can use `/api/search`.
   - Email can use `/api/email/messages`, `/api/email/draft`, `/api/email/send` with approval handling.
   - Calendar can use `/api/calendar/events` with approval handling.
   - Do not invent WhatsApp/Telegram REST panels because no corresponding API routes exist; expose their status through Tools Ops unless backend routes already exist later.

9. Add backup/restore access only as explicit admin flows.
   - Use existing `/api/system/backups`, `/api/system/backup`, and `/api/system/restore`.
   - Restore is potentially destructive; preserve existing backend behavior and surface errors directly.

10. Keep Data Inspector as the broad fallback for advanced visibility.
   - It already exposes backend tables allowed by `ALLOWED_DATA_TABLES` in `src/api/server.py`.
   - Refine it to use `columns`, `total_rows`, and `limit` before building new custom panels.