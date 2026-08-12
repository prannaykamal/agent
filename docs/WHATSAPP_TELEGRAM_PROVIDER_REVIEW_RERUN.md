# WhatsApp / Telegram Provider Architecture Review Rerun

## Verdict

**APPROVED WITH CAVEATS**

The previous architecture blockers from `docs/WHATSAPP_TELEGRAM_PROVIDER_REVIEW.md` are fixed. It is now safe to proceed to real WhatsApp/Telegram provider onboarding from the backend architecture perspective, provided onboarding uses test accounts/credentials and does not bypass the existing HITL send policy.

The remaining caveat is frontend-only: Tools Ops labels WhatsApp/Telegram as Direct API providers and blocks MCP discovery for them, but the shared provider list still renders a generic `Refresh Metadata` button for direct providers. Clicking it does not call MCP discovery; it displays a not-applicable notice. This is not a backend/provider onboarding blocker, but hiding or relabeling that control for direct providers would reduce operator confusion.

## Review Inputs

Reviewed:

- `docs/WHATSAPP_TELEGRAM_PROVIDER_REVIEW.md`
- `src/mcp_gateway/mcp_bridge.py`
- `src/mcp_gateway/registry.py`
- `src/harness/graph.py`
- `src/api/server.py`
- `src/external_providers/common.py`
- `src/tools/mcp_provider_config.py`
- `src/tools/registry_types.py`
- `src/tools/mcp_schema.py`
- `src/tools/observability.py`
- `frontend/src/components/ToolsCockpit.jsx`
- `frontend/src/components/ToolsOpsCockpit.jsx`
- `frontend/src/components/OverviewCockpit.jsx`
- relevant tests

## Previous Blockers

| Previous blocker | Rerun result | Evidence |
| --- | --- | --- |
| Stale WhatsApp/Telegram MCP discovery could run from `.agent/mcp_config.json` | Fixed | `src/mcp_gateway/mcp_bridge.py` imports `target_mcp_provider_ids()`, builds an allowlist, and skips any server name not in that set before transport/client creation. |
| Configured direct WhatsApp/Telegram tools appeared under `/api/tools.mcp_tools` | Fixed | `/api/tools` now returns `external_api_tools`; configured WhatsApp/Telegram tools appear there, not in `mcp_tools`. |
| Direct provider error redaction did not scrub arbitrary token values | Fixed | `src/external_providers/common.py` redacts configured `WHATSAPP_API_TOKEN` and `TELEGRAM_BOT_TOKEN` values in text, payloads, response previews, and `to_text()` output. |

## Verification Details

### 1. Stale MCP Discovery

Pass.

`load_live_mcp_tools()` now filters discovery through the target MCP provider allowlist:

- `search_tavily`
- `search_duckduckgo`
- `google_calendar`
- `gmail`

The stale `whatsapp` and `telegram` entries are ignored even if a config file contains them. The regression test `test_t6_live_mcp_bridge_skips_stale_whatsapp_telegram_config` seeds old entries and verifies only the allowed Gmail config is attempted, with no WhatsApp/Telegram warning output.

The local `.agent/mcp_config.json` also no longer contains `whatsapp`, `telegram`, `whatsapp-mcp`, or `telegram-mcp`.

### 2. `/api/tools` Classification

Pass.

Observed sanity check with fake direct provider env vars:

```text
keys ['external_api_tools', 'mcp_tools', 'personal_os_tools', 'total_tools']
mcp []
external ['whatsapp_read', 'whatsapp_send', 'telegram_read', 'telegram_send']
mcp_ids ['search_tavily', 'search_duckduckgo', 'google_calendar', 'gmail']
external_ids ['whatsapp_api:configured', 'telegram_bot_api:configured']
detail 404 404
```

So:

- `mcp_tools` does not contain `whatsapp_read`, `whatsapp_send`, `telegram_read`, or `telegram_send`.
- `external_api_tools` contains the direct provider tools when configured.
- `/api/tools/mcp/providers/whatsapp` returns 404.
- `/api/tools/mcp/providers/telegram` returns 404.

### 3. Direct Provider Redaction

Pass.

The updated tests cover:

- provider status redacts fake configured WhatsApp/Telegram tokens
- fake Telegram token appearing in failed URL-like exception text is redacted
- fake WhatsApp token appearing in failed header/error text is redacted
- redacted values are applied to `to_text()`, `to_dict()`, audit metadata, and response previews

No raw token value was observed through the reviewed API/status paths.

### 4. MCP Providers Preserved

Pass.

The MCP provider registry remains limited to:

- Gmail MCP: `gmail`
- Google Calendar MCP: `google_calendar`
- Search MCP: `search_tavily`, `search_duckduckgo`

WhatsApp and Telegram are not MCP providers.

### 5. Frontend Behavior

Pass with caveat.

Frontend status sources are correct:

- `OverviewCockpit.jsx` fetches `/api/tools/mcp/providers` and `/api/tools/external/providers` separately.
- `ToolsOpsCockpit.jsx` fetches both provider layers and labels Direct API providers separately from MCP providers.
- `ToolsCockpit.jsx` renders the `external_api` registry group as Direct API Providers.

Caveat:

- `ToolsOpsCockpit.jsx` still renders a shared `Refresh Metadata` button for each provider row, including direct API providers. The click handler guards `whatsapp_api` and `telegram_bot_api` and does not call MCP discovery; it shows an MCP-not-applicable notice instead. This is safe, but the control should ideally be hidden or relabeled for direct providers in a frontend polish pass.

### 6. Regression Test Coverage

Pass.

Regression tests now cover:

- stale WhatsApp/Telegram MCP config ignored
- no WhatsApp/Telegram MCP warning output from stale config
- direct WhatsApp/Telegram tools excluded from `mcp_tools`
- direct WhatsApp/Telegram tools included in `external_api_tools`
- token redaction for provider status and invocation errors
- Gmail/Calendar/Search MCP provider set unchanged
- `/api/tools/mcp/providers/whatsapp` and `/telegram` return 404

## Test Results

Requested test command:

```powershell
python -m pytest tests/test_tools_t6_mcp_api.py tests/test_tools_t7_no_local_provider_implementations.py tests/test_tools_t8_policy_classification.py tests/test_tools_t9_observability_api.py tests/test_frontend_api.py tests/test_api_server.py -q
```

Result:

```text
35 passed, 1 warning in 33.16s
```

Note: LangSmith emitted network/proxy telemetry errors after pytest completed. They did not fail pytest.

Frontend build:

```powershell
cd frontend
npm run build
cd ..
```

Result:

- sandboxed run failed with the known esbuild child-process `spawn EPERM`
- escalated rerun passed:

```text
vite v5.4.21 building for production...
43 modules transformed.
built in 2.89s
```

Removed-route scan:

```powershell
rg -n "/api/browser|/api/github" frontend/src tests
```

Result:

- no frontend source calls
- matches only in tests asserting removed-route absence or forbidden endpoint strings

## Remaining Blockers

None.

## Safe To Proceed?

**Yes, safe to proceed to real provider onboarding with caveats.**

Do not add real sends without using the existing HITL approval path. Use safe provider smoke-test accounts and keep the frontend Direct API refresh-control caveat on the cleanup list.
