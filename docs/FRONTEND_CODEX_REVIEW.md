# Frontend Codex Review

## 1. Review Verdict

**NOT APPROVED** for tagging `frontend-integration-v1`.

The frontend integration is substantially advanced and most F1-F8 areas are present, but two local frontend/backend integration blockers remain:

1. `frontend/src/components/MemoryObservabilityCockpit.jsx` has a broken retrieval trace action. The rendered button references `runTrace`, which is not defined, while the implemented helper is `handleTrace`. That helper also calls a non-existent `GET /api/memory/observability/trace` endpoint instead of the existing `POST /api/memory/observability/retrieval/trace` endpoint in `src/api/server.py`.
2. `frontend/src/components/MemoryCockpit.jsx` sends arrays to `POST /api/skills`, but `src/api/server.py` defines `SkillRequest.trigger_keywords` and `SkillRequest.execution_steps` as strings. A direct verification request returns HTTP 422. The active skill list rendering also treats these fields as arrays, while the backend compatibility path stores/returns string values.

A required frontend/API smoke test also failed because `/api/chat` returned HTTP 500 with `Agent harness error: Connection error.` The captured logs show external MCP/LangSmith connectivity failures, so this is classified separately from the local frontend implementation blockers. It still means the required test batch did not pass.

## 2. Blueprint Compliance Checklist

| Area | Verdict | Evidence |
|---|---|---|
| API helper consistency | Pass | `frontend/src/api/client.js` centralizes requests with `api.get/post/put/patch/delete` and extracts FastAPI `detail` errors. `rg -n "fetch\(" frontend/src/components` returned no matches. |
| Chat approval/HITL states | Pass with caveat | `ChatCockpit.jsx` reads `pending_approval_id`, `approval_status`, and `retrieval_triggered`. `ApprovalInbox.jsx` handles procedural metadata and error outcomes. Caveat: chat smoke test failed due `/api/chat` connection error. |
| Overview/integration status | Pass with caveat | `OverviewCockpit.jsx` calls `/api/integrations/status`, `/api/tools/mcp/providers`, and `/api/memory/observability/workers`. Caveat: it references `workerObs.active_workers`/`stale_workers`, while backend worker summary uses `active`/`stale` in `src/memory/observability.py`; this may display fallback/zero values rather than exact worker truth. |
| Cron scheduler UI | Pass | `ScheduledCockpit.jsx` uses durable `/api/tools/cron/*` APIs, schedule/run filters, detail inspection, patch update, and delete/cancel. No primary legacy `/api/scheduled` usage found in components. |
| Tools Ops | Pass | `ToolsOpsCockpit.jsx` calls `/api/tools/status`, provider detail, provider discovery refresh, and standalone calls/results/audit/blocked observability endpoints. |
| Memory browsing | Pass | `MemoryCockpit.jsx` preserves `/api/memory/full` browsing. |
| Memory fact write | Pass | `MemoryCockpit.jsx` posts `{category, fact_text}` to `/api/memory/fact`, matching `FactRequest` in `src/api/server.py`. |
| Skills API wiring | **Blocker** | `MemoryCockpit.jsx` posts arrays for `trigger_keywords` and `execution_steps`; backend expects strings. Verified HTTP 422. |
| Backup/restore | Pass | `OverviewCockpit.jsx` calls `/api/system/backups`, `/api/system/backup`, and `/api/system/restore`, with explicit restore confirmation state. |
| Data Inspector | Pass | `DataCockpit.jsx` uses `columns`, `total_rows`, `rows`, and `limit`; it remains read-only. |
| Removed endpoints | Pass | No frontend source calls `/api/browser` or `/api/github`; strings appear only in tests asserting absence. |
| Scope compliance | Pass | `git diff -- frontend/src docs/FRONTEND_FINAL_STATUS.md` was empty before this review doc was written, and `git status --short` was clean. No backend/API/dependency changes were made by this review. |

## 3. F1-F8 Implementation Checklist

| Increment | Expected | Review result |
|---|---|---|
| F1 API helper and approval state | Central API helper; chat approval state; richer approval inbox | Implemented. Raw component `fetch()` scan is clean. |
| F2 Overview/provider status | Use current MCP/provider/integration status; avoid treating `/api/system/health.worker_status` as exact truth | Mostly implemented. Provider/integration APIs are wired. Worker summary field mismatch needs cleanup before tag. |
| F3 Cron detail/filter/update | Durable cron APIs, filters, detail, patch, cancel, run states | Implemented. |
| F4 Tools Ops/MCP discovery | `/api/tools/status`, provider detail, metadata-only discovery, standalone observability | Implemented. |
| F5 Memory facts and skills | `POST /api/memory/fact`; `/api/skills` list/create/delete | Fact write implemented. Skill create/list rendering has contract mismatch blocker. |
| F6 Backup/restore | List/create/restore with explicit confirmation and backend error surfacing | Implemented. |
| F7 Data Inspector | Use `columns`, `total_rows`, `rows`, safe `limit`, read-only | Implemented. |
| F8 Final verification/status | Final status doc and build/test verification | Partially met. Build passes after sandbox escalation, but required pytest batch fails and local blockers remain. |

## 4. API Contract Verification

Verified contracts:

- `frontend/src/api/client.js` handles JSON responses, non-JSON responses, FastAPI string `detail`, FastAPI validation-list `detail`, `message`, and `error` fields.
- `ChatCockpit.jsx` payload matches `ChatRequest` in `src/api/server.py`.
- `MemoryCockpit.jsx` fact payload matches `FactRequest` in `src/api/server.py`.
- `ScheduledCockpit.jsx` create and patch payloads match `CronScheduleRequest` and `CronSchedulePatchRequest` fields in `src/api/server.py`.
- `DataCockpit.jsx` consumes `/api/data/table/{table_name}?limit={limit}` response fields `columns`, `total_rows`, and `rows`.
- `ApprovalInbox.jsx` posts `{decision}` with `APPROVED` or `REJECTED` strings as required by `DecisionRequest`.

Contract blockers:

- `MemoryCockpit.jsx:92-105` converts skill keywords and steps into arrays and posts them to `/api/skills`. `src/api/server.py:90-94` defines `SkillRequest.trigger_keywords: str` and `execution_steps: str`. Direct check returned:
  - HTTP 422
  - `trigger_keywords`: `Input should be a valid string`
  - `execution_steps`: `Input should be a valid string`
- `MemoryCockpit.jsx:370-381` renders `s.trigger_keywords.map(...)` and `s.execution_steps.map(...)`. The backend procedural compatibility facade in `src/memory/procedural.py` treats both fields as strings.
- `MemoryObservabilityCockpit.jsx:98-103` defines `handleTrace`, but `MemoryObservabilityCockpit.jsx:164` binds `onClick={runTrace}`. No `runTrace` function exists.
- `MemoryObservabilityCockpit.jsx:103` calls `/api/memory/observability/trace` with GET query parameters. The actual backend route is `POST /api/memory/observability/retrieval/trace` at `src/api/server.py:414`.

## 5. Removed Endpoint Verification

Commands run:

```powershell
rg -n "/api/browser|/api/github" frontend/src tests
```

Result:

- No matches in `frontend/src`.
- Matches exist only in tests that assert removed endpoint absence, such as `tests/test_tools_t9_no_write_controls.py`, `tests/test_tools_t10_final_static_scans.py`, and `tests/test_tools_t10_docs_alignment.py`.

Verdict: removed endpoint verification passes.

## 6. Raw Fetch / API Helper Verification

Command run:

```powershell
rg -n "fetch\(" frontend/src/components
```

Result: no matches.

`frontend/src/api/client.js` is used by the reviewed components and cleanly extracts FastAPI `detail` error messages. Verdict: API helper consistency passes.

## 7. Test Results

Required pytest command:

```powershell
python -m pytest tests/test_frontend_api.py tests/test_p2_frontend_smoke.py tests/test_p3_frontend.py tests/test_api_server.py -q
```

Result: **failed**.

- 22 passed
- 1 failed
- Failure: `tests/test_p2_frontend_smoke.py::test_p2_4_chat_send_flow_browser_ui`
- Cause observed from response detail: `POST /api/chat` returned HTTP 500 with `{detail: "Agent harness error: Connection error."}`.
- Captured logs showed MCP provider discovery failures for unconfigured providers and LangSmith network/proxy connection failures.

Classification: not a frontend component regression by itself, but the required frontend/API smoke batch is not green. Do not call the test set passing.

Additional direct contract verification:

```powershell
POST /api/skills with frontend-shaped arrays
```

Result: HTTP 422 because backend expects strings for `trigger_keywords` and `execution_steps`.

Full suite: not run. It was not feasible or useful to run the full suite after the required smoke batch failed and local frontend blockers were identified.

## 8. Frontend Build Result

Initial required build command from `frontend/`:

```powershell
npm run build
```

Sandbox result: failed with `Error: spawn EPERM` while Vite/esbuild tried to spawn its helper process.

Escalated rerun result:

```powershell
npm run build
```

Result: **passed**.

- Vite transformed 43 modules.
- Output included `dist/index.html`, `dist/assets/index-D7wpfNOC.css`, and `dist/assets/index-DAIREnUB.js`.
- Build completed successfully in about 3.20s.

Important caveat: the build does not catch the `MemoryObservabilityCockpit.jsx` runtime `runTrace` reference issue.

## 9. Remaining Risks or Caveats

- Memory Ops retrieval trace is currently broken at runtime due undefined `runTrace` and wrong endpoint/method.
- Active skill creation is currently broken against the backend contract due array-vs-string payload mismatch.
- Active skill rendering may crash or render incorrectly when backend returns string fields and the component calls `.map()` on them.
- Overview worker telemetry may not accurately reflect backend fields because frontend expects `active_workers` and `stale_workers`, while the memory worker endpoint summary uses `active` and `stale`.
- `/api/chat` smoke test failed due a connection error. Logs indicate external-provider/tracing connectivity, but the required smoke batch is still red.
- No full suite result is available for this review.

## 10. Exact Recommendation

**Fix listed blockers first. Do not tag `frontend-integration-v1` yet.**

Minimum fixes before tagging:

1. In `MemoryObservabilityCockpit.jsx`, call the existing `POST /api/memory/observability/retrieval/trace` endpoint through `api.post(...)`, and bind the rendered button to the actual trace handler.
2. In `MemoryCockpit.jsx`, send `trigger_keywords` and `execution_steps` as strings to `/api/skills`, and render skill fields defensively whether backend returns strings or arrays.
3. Align Overview worker summary field access with the actual `/api/memory/observability/workers` response shape or verify the current fallback is intentional.
4. Rerun the required pytest batch and frontend build. If `/api/chat` still fails only because of external quota/network/provider issues, record that separately with response details.

Final recommendation: **NOT APPROVED; fix blockers before tagging `frontend-integration-v1`.**