# WhatsApp / Telegram Provider Architecture Review

## Verdict

**NOT APPROVED**

The main provider split is partially implemented: `/api/tools/mcp/providers` no longer reports `whatsapp` or `telegram`, direct provider status exists for `whatsapp_api` and `telegram_bot_api`, and policy metadata keeps send actions approval-required. However, two blockers remain before real provider onboarding:

1. The live MCP bridge still attempts discovery for `whatsapp` and `telegram` if those servers remain in `.agent/mcp_config.json`.
2. Configured WhatsApp/Telegram direct API tools still appear under the legacy `/api/tools.mcp_tools` response bucket.

There is also a non-blocking but important privacy hardening gap around redacting actual configured token values from provider invocation errors.

## Review Inputs

Reviewed:

- `src/external_providers/*`
- `src/tools/mcp_provider_config.py`
- `src/tools/registry_types.py`
- `src/tools/mcp_schema.py`
- `src/tools/observability.py`
- `src/mcp_gateway/communication.py`
- `src/mcp_gateway/registry.py`
- `src/api/server.py`
- `src/config.py`
- `frontend/src/components/ToolsOpsCockpit.jsx`
- `frontend/src/components/OverviewCockpit.jsx`
- Relevant tests and docs

## Checklist

| Check | Result | Notes |
| --- | --- | --- |
| WhatsApp/Telegram absent from MCP provider registry/status | Pass | `TARGET_MCP_PROVIDER_DEFAULTS` contains only search, Google Calendar, and Gmail providers in `src/tools/mcp_provider_config.py`. |
| `/api/tools/mcp/providers/whatsapp` and `/telegram` return not found | Pass | Covered by `tests/test_tools_t6_mcp_api.py`; requested pytest batch passed. |
| Direct provider status exists | Pass | `src/external_providers/registry.py` exposes `whatsapp_api` and `telegram_bot_api`; `/api/tools/external/providers` exists in `src/api/server.py`. |
| Token values not exposed in status/frontend | Pass for status, caveat for invocation errors | Status responses expose env var names, not values. Invocation error redaction is weaker; see Caveat C1. |
| WhatsApp/Telegram send approval required | Pass | `whatsapp_send` and `telegram_send` remain High risk and policy tests assert approval-required behavior. |
| Gmail/Calendar/Search MCP behavior unchanged | Pass | MCP provider set remains `search_tavily`, `search_duckduckgo`, `google_calendar`, `gmail`. |
| Frontend displays WhatsApp/Telegram as direct API providers | Pass | Tools Ops and Overview fetch `/api/tools/external/providers` and label `external_api` providers as Direct API. |
| No browser/code sandbox references returned | Pass for runtime/frontend | Scan found only historical docs/removal tests, not runtime/frontend source references. |
| Tests meaningful beyond happy path | Partial | API absence, redaction, policy, and unavailable paths are covered; missing tests for old MCP config discovery and `/api/tools` grouping. |

## Findings

### B1. WhatsApp/Telegram MCP discovery can still run from `.agent/mcp_config.json`

**Severity:** Blocker

`src/mcp_gateway/mcp_bridge.py` loads every server in `.agent/mcp_config.json` and calls `client.list_tools()` without filtering to the target MCP provider set:

- `src/mcp_gateway/mcp_bridge.py:52`
- `src/mcp_gateway/mcp_bridge.py:69`
- `src/mcp_gateway/mcp_bridge.py:93`

The current `.agent/mcp_config.json` still contains:

- `.agent/mcp_config.json:52` `whatsapp`
- `.agent/mcp_config.json:64` `telegram`

During review, calling `/api/tools` with direct provider env vars configured produced MCP bridge warnings for both old servers:

- `Failed to load tools from server 'whatsapp'`
- `Failed to load tools from server 'telegram'`

This violates the expected architecture requirement that WhatsApp/Telegram have no MCP discovery/status/tool registration remaining.

**Recommended fix:** Filter live MCP bridge discovery through the allowed MCP provider registry, or remove/ignore `whatsapp` and `telegram` entries from `.agent/mcp_config.json` during config loading. Add a regression test that seeds old MCP config entries and proves no WhatsApp/Telegram MCP discovery is attempted.

### B2. Configured direct WhatsApp/Telegram tools still appear under `/api/tools.mcp_tools`

**Severity:** Blocker

`/api/tools` still returns only two buckets: `personal_os_tools` and `mcp_tools`:

- `src/api/server.py:593`
- `src/api/server.py:596`
- `src/api/server.py:599`

`get_mcp_tool_catalog()` is still sourced from `src/mcp_gateway/registry.py`, where `ALL_MCP_TOOLS` includes:

- `whatsapp_read`
- `whatsapp_send`
- `telegram_read`
- `telegram_send`

References:

- `src/mcp_gateway/registry.py:89`
- `src/mcp_gateway/registry.py:92`
- `src/mcp_gateway/registry.py:93`
- `src/mcp_gateway/registry.py:122`

When fake direct provider env vars were configured during review, `/api/tools` returned:

```text
mcp_tools: ['whatsapp_read', 'whatsapp_send', 'telegram_read', 'telegram_send']
```

The metadata is correctly marked as `ImplementationType.EXTERNAL_API` later in the registry, but the public compatibility catalog still classifies them under the `mcp_tools` response bucket. That conflicts with “WhatsApp is direct API provider only” and “Telegram is direct Bot API provider only.”

**Recommended fix:** Preserve `/api/tools` response compatibility if required, but do not place direct API tools in `mcp_tools`. Add an additive direct-provider bucket or omit unavailable direct tools from the legacy MCP bucket, and update frontend/tests accordingly.

## Caveats

### C1. Direct provider error redaction does not scrub arbitrary configured token values

**Severity:** Medium

`src/external_providers/common.py:redact_text()` redacts strings containing marker words such as `token`, `secret`, and `authorization`, but it does not replace arbitrary configured secret values. Telegram send builds the token into the URL:

- `src/external_providers/common.py:105`
- `src/external_providers/telegram_bot_api.py:64`
- `src/external_providers/telegram_bot_api.py:66`

WhatsApp sends the token in the `Authorization` header:

- `src/external_providers/whatsapp_api.py:64`
- `src/external_providers/whatsapp_api.py:78`

Status endpoints are currently safe, and tests verify fake token values are not present in provider status responses. The remaining gap is invocation error handling if a provider/client exception echoes a full URL or header-like value.

**Recommended fix:** Redact actual configured env var values for all direct provider secret env vars before returning or storing provider error text.

### C2. Tests do not cover stale MCP config entries or `/api/tools` direct-provider grouping

**Severity:** Medium

The tests cover the new happy and unavailable paths, but they did not catch B1 or B2. In particular, missing cases are:

- `.agent/mcp_config.json` contains old `whatsapp`/`telegram` servers, but MCP discovery must skip them.
- Direct providers are configured, but `/api/tools` must not list them as MCP tools.
- Direct provider invocation errors must redact arbitrary token values, not just marker-looking keys.

## Test Results

Requested pytest batch:

```powershell
python -m pytest tests/test_tools_t6_mcp_api.py tests/test_tools_t7_no_local_provider_implementations.py tests/test_tools_t8_policy_classification.py tests/test_tools_t9_observability_api.py tests/test_frontend_api.py tests/test_api_server.py -q
```

Result:

```text
32 passed, 1 warning in 30.25s
```

Note: LangSmith telemetry emitted network/proxy errors after pytest completed. These did not fail the test run.

Frontend build:

```powershell
cd frontend
npm run build
cd ..
```

Result:

- First sandboxed run failed with `spawn EPERM` from esbuild.
- Escalated rerun passed:

```text
vite v5.4.21 building for production...
43 modules transformed.
built in 2.48s
```

## Static Scan Notes

Browser/code sandbox scan:

- No runtime/frontend source references were found.
- Remaining matches are historical documentation or tests asserting removal/blocked behavior.

WhatsApp/Telegram MCP scan:

- MCP provider status endpoints correctly omit `whatsapp` and `telegram`.
- Stale MCP config entries still exist in `.agent/mcp_config.json`.
- The live MCP bridge still attempts those stale entries.

## Safe To Proceed?

**No. Do not proceed to real WhatsApp/Telegram provider onboarding yet.**

Fix the MCP bridge/config filtering and `/api/tools` catalog classification first, then add regression tests for stale MCP config and configured direct-provider catalog behavior. After that, real provider onboarding can proceed with a much cleaner boundary.

