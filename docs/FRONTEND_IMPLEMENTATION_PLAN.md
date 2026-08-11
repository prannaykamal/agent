# ASTRA Frontend Implementation Plan

## 1. Confirmed Frontend Gaps from Blueprint

Verification against the active codebase (`src/api/server.py` and `frontend/src/components/*`) confirms the following gaps:

- **Approval-Pending State Gaps (`ChatCockpit.jsx` & `ApprovalInbox.jsx`)**:
  - `POST /api/chat` returns `pending_approval_id` and `approval_status` when a tool requires approval, but `ChatCockpit.jsx` only appends response text and loop trace without surfacing an actionable approval status or link.
  - `ApprovalInbox.jsx` handles generic approve/reject decisions, but does not display procedural skill promotion metadata (`procedural_skill_approval` returned by `POST /api/approvals/{id}/decision`) or handle provider-unavailable error details cleanly.

- **Provider & System Telemetry Realignment Gaps (`OverviewCockpit.jsx`)**:
  - `OverviewCockpit.jsx` fetches `/api/system/health`, which statically returns `worker_status: "RUNNING"` and environment provider flags. It does not reflect live MCP provider statuses from `GET /api/tools/mcp/providers` or capability readiness from `GET /api/integrations/status`.

- **Cron Detail, Patch & Filtering Gaps (`ScheduledCockpit.jsx`)**:
  - `ScheduledCockpit.jsx` calls `GET/POST/DELETE` on `/api/tools/cron/schedules` and `GET /api/tools/cron/runs?limit=20`.
  - It lacks schedule detail inspection (`GET /api/tools/cron/schedules/{schedule_id}`), safe schedule update/pause (`PATCH /api/tools/cron/schedules/{schedule_id}`), schedule status filtering (`status`), run filtering by schedule/status (`schedule_id`, `status`), and display of run execution states (`WAITING_FOR_APPROVAL`, `FAILED_RETRYABLE`, `FAILED_TERMINAL`, `CANCELLED`).

- **Tools Ops & MCP Provider Refresh Gaps (`ToolsOpsCockpit.jsx`)**:
  - `ToolsOpsCockpit.jsx` lists MCP providers from `GET /api/tools/mcp/providers`, but does not support provider detail drill-down (`GET /api/tools/mcp/providers/{provider_id}`) or explicit discovery refresh (`POST /api/tools/mcp/providers/{provider_id}/discover`).
  - It ignores summary tool status (`GET /api/tools/status`) and standalone observability endpoints (`/calls`, `/results`, `/audit`, `/blocked`).

- **Skills & Memory Write-Path Gaps (`MemoryCockpit.jsx` & `MemoryObservabilityCockpit.jsx`)**:
  - `MemoryCockpit.jsx` reads `/api/memory/full`, but provides no UI for explicit permanent fact entry (`POST /api/memory/fact`) or procedural skill management (`GET/POST/DELETE /api/skills`).
  - `MemoryObservabilityCockpit.jsx` fetches job/worker queues, but lacks filter controls (`status`, `job_type`, `session_id`, `include_payload`, `stale_after_seconds`).

- **System Backup/Restore & Integration Status Gaps**:
  - No frontend component exposes backup listing (`GET /api/system/backups`), backup creation (`POST /api/system/backup`), or backup restoration (`POST /api/system/restore`).
  - No component displays the integration readiness breakdown from `GET /api/integrations/status`.

- **Data Inspector Parameter Gaps (`DataCockpit.jsx`)**:
  - `DataCockpit.jsx` calls `GET /api/data/table/{table_name}`, but ignores `columns`, `total_rows`, and `limit` in the returned JSON.

---

## 2. Existing Components to Preserve

All 11 existing cockpit panels and the top-level application shell will be preserved without altering visual design, styling tokens, or navigation layout:

1. `frontend/src/App.jsx`: Core application layout, tab switching, session ID management.
2. `frontend/src/components/ChatCockpit.jsx`: Chat message history, session switcher/renamer, model dropdowns.
3. `frontend/src/components/LoopCockpit.jsx`: Step-by-step reasoning and tool execution trace.
4. `frontend/src/components/OverviewCockpit.jsx`: Telemetry summary cards and active session status.
5. `frontend/src/components/MemoryCockpit.jsx`: Knowledge browsing (facts, episodes, SOUL.md, SKILL.md, MEMORY.md).
6. `frontend/src/components/MemoryObservabilityCockpit.jsx`: Pipeline health, job summaries, worker status, retrieval trace runner.
7. `frontend/src/components/ApprovalInbox.jsx`: HITL pending approval list and decision controls.
8. `frontend/src/components/ToolsCockpit.jsx`: Tool catalog registry groups and policy status badges.
9. `frontend/src/components/ToolsOpsCockpit.jsx`: Provider status table, Personal OS status/actions/audit log.
10. `frontend/src/components/ScheduledCockpit.jsx`: Schedule manager, create form, run log table.
11. `frontend/src/components/TaskBoard.jsx`: Task and sub-agent board.
12. `frontend/src/components/DataCockpit.jsx`: Database table selector and raw data grid.

---

## 3. Backend APIs to Wire or Refine

The following backend endpoints in `src/api/server.py` will be wired or refined in existing components:

| Endpoint | Method | Component | Purpose / Target Refinement |
|---|---|---|---|
| `/api/chat` | POST | `ChatCockpit.jsx` | Surface `pending_approval_id`, `approval_status`, `retrieved_memories` inline |
| `/api/approvals/{id}/decision` | POST | `ApprovalInbox.jsx` | Display procedural skill approval details and error responses cleanly |
| `/api/integrations/status` | GET | `OverviewCockpit.jsx` / `ToolsOpsCockpit.jsx` | Render provider-managed integration readiness |
| `/api/tools/mcp/providers/{id}` | GET | `ToolsOpsCockpit.jsx` | Inspect detailed provider configuration and tool list |
| `/api/tools/mcp/providers/{id}/discover` | POST | `ToolsOpsCockpit.jsx` | Trigger safe metadata rediscovery for a specific provider |
| `/api/tools/status` | GET | `ToolsOpsCockpit.jsx` | Display high-level tool status summary |
| `/api/tools/cron/schedules/{id}` | GET | `ScheduledCockpit.jsx` | View full schedule configuration and target payload |
| `/api/tools/cron/schedules/{id}` | PATCH | `ScheduledCockpit.jsx` | Safely update schedule parameters (expression, payload, status) |
| `/api/tools/cron/schedules` | GET | `ScheduledCockpit.jsx` | Filter schedule list by `status` |
| `/api/tools/cron/runs` | GET | `ScheduledCockpit.jsx` | Filter run history by `schedule_id` and `status` |
| `/api/memory/fact` | POST | `MemoryCockpit.jsx` | Add explicit permanent semantic facts |
| `/api/skills` | GET/POST/DELETE | `MemoryCockpit.jsx` / `ToolsCockpit.jsx` | Active procedural skill CRUD operations |
| `/api/system/backups` | GET | `OverviewCockpit.jsx` / System Modal | List available system backups |
| `/api/system/backup` | POST | `OverviewCockpit.jsx` / System Modal | Create on-demand system backup |
| `/api/system/restore` | POST | `OverviewCockpit.jsx` / System Modal | Restore system state from backup path with confirmation |
| `/api/data/table/{table_name}` | GET | `DataCockpit.jsx` | Utilize `columns`, `total_rows`, and `limit` fields |

---

## 4. Components Likely to Be Modified

- `frontend/src/components/ChatCockpit.jsx`
- `frontend/src/components/ApprovalInbox.jsx`
- `frontend/src/components/OverviewCockpit.jsx`
- `frontend/src/components/ScheduledCockpit.jsx`
- `frontend/src/components/ToolsOpsCockpit.jsx`
- `frontend/src/components/MemoryCockpit.jsx`
- `frontend/src/components/MemoryObservabilityCockpit.jsx`
- `frontend/src/components/DataCockpit.jsx`

---

## 5. Implementation Order

1. **Step 1: API Adapter Helper & Error Handling Standardization**
   - Create lightweight response/error handling helper to extract `detail` messages from FastAPI non-2xx responses.
2. **Step 2: Approval State & HITL Integration Refinement**
   - In `ChatCockpit.jsx`, detect `pending_approval_id` from `/api/chat` and present an inline approval indicator linked to approvals.
   - In `ApprovalInbox.jsx`, render procedural skill approval results and handle failure/unavailable responses.
3. **Step 3: Overview & System Telemetry Alignment**
   - Wire `GET /api/integrations/status` in `OverviewCockpit.jsx` to show live MCP integration health alongside system health.
4. **Step 4: Cron Scheduler Filtering & Safe Editing**
   - In `ScheduledCockpit.jsx`, add status filter tabs for schedules and runs, wire `GET /api/tools/cron/schedules/{id}` detail modal, and wire `PATCH /api/tools/cron/schedules/{id}`.
5. **Step 5: Tools Ops & MCP Discovery Refinement**
   - In `ToolsOpsCockpit.jsx`, wire provider detail view, `POST /discover` refresh button, and `/api/tools/status` summary.
6. **Step 6: Memory & Skill Write Paths**
   - In `MemoryCockpit.jsx`, add permanent fact creation form (`POST /api/memory/fact`) and active skills table with create/delete capabilities (`/api/skills`).
7. **Step 7: Backup/Restore Operations UI**
   - Add backup management (list, create, restore) in Overview or Tools Ops with safety prompts.
8. **Step 8: Data Inspector Refinement**
   - In `DataCockpit.jsx`, expose table column headers, total row counts, and configurable row limits.

---

## 6. Risks and Unclear Areas

- `Needs verification`: Calendar update endpoint (`PUT /api/calendar/events/{id}`) executes directly in `server.py`, whereas create and delete require approvals. Verification is needed before adding frontend event edit controls.
- `Needs verification`: System restore (`POST /api/system/restore`) overwrites the database and system files. The UI must mandate path confirmation to prevent accidental data loss.
- `Needs verification`: MCP provider availability relies on external configs (`.agent/mcp_config.json`). Unconfigured providers will return `unavailable` or `discovery_failed`, which must be handled gracefully in the UI.
- `Needs verification`: `OverviewCockpit.jsx` displays `worker_status: "RUNNING"` from `/api/system/health`, which is static. Real worker staleness should be cross-referenced with `GET /api/memory/observability/workers`.

---

## 7. Verification Plan & Tests to Run After Each Step

- **Build Verification**:
  - Run frontend build check (`npm run build` or Vite compile) in `frontend/` directory to ensure zero syntax or JSX compilation errors.
- **API Wiring & Runtime Verification**:
  - Verify endpoints using browser dev tools or Python test scripts against the running FastAPI server (`http://localhost:8000`).
  - Test approval decision flow end-to-end.
  - Verify cron schedule creation, filtering, update, and cancellation.
  - Verify backup list/create responses and memory fact insertion.
