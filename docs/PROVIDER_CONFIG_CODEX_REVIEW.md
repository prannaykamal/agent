# Provider Config Codex Review

## Verdict

NOT APPROVED

The provider onboarding/config input system is close, and the requested tests/build pass. However, it is not safe to enter real MCP provider credentials yet because MCP discovery error redaction does not redact arbitrary configured secret values when an exception echoes the value without a marker word such as `token`, `secret`, or `authorization`.

Direct WhatsApp/Telegram provider status and direct invocation error redaction look covered by tests. The blocker is specifically the MCP validation/status path for Gmail, Google Calendar, and Tavily/DuckDuckGo Search credentials.

## Reviewed Files

- `src/tools/provider_config.py`
- `src/api/server.py`
- `frontend/src/components/ToolsOpsCockpit.jsx`
- `tests/test_tools_t6_mcp_api.py`
- `.gitignore`
- `.env.example`
- `.agent/mcp_config.example.json`
- `docs/provider-onboarding.md`
- `docs/PROVIDER_VALIDATION_REPORT.md`
- `docs/tools-operator-runbook.md`

## Config API Safety

| Check | Result | Notes |
| --- | --- | --- |
| `GET /api/config/providers` does not return direct provider raw secrets | PASS | Direct API saved values are redacted by field name in `src/tools/provider_config.py`. Tests cover WhatsApp and Telegram fake tokens. |
| `POST /api/config/providers/{provider_id}` accepts config safely | PASS WITH CAVEAT | Unknown fields are ignored and responses are redacted. MCP config writes to `.agent/mcp_config.json`; direct API config writes to `.env`. |
| `DELETE /api/config/providers/{provider_id}/secret` clears intended secret fields | PASS | Clear logic targets fields marked `secret=True`; tests cover Telegram secret removal. |
| `POST /api/config/providers/{provider_id}/validate` is write-safe | PASS | MCP validation uses provider status/discovery; direct API validation calls status only. Tests assert Telegram validation does not call send. |
| Validation does not send messages/email or create calendar events | PASS | No send/create paths are invoked by `validate_provider_config()`. |

## Storage Safety

| Check | Result | Notes |
| --- | --- | --- |
| Real `.env` ignored | PASS | `.gitignore` ignores `.env` and `.env.*` while allowing `.env.example`. |
| Runtime `.agent/*` config ignored | PASS | `.gitignore` ignores `.agent/*` while allowing `.agent/mcp_config.example.json`. |
| `.env.example` safe | PASS | Contains placeholders only. |
| `.agent/mcp_config.example.json` safe | PASS | Contains disabled placeholder MCP configs only; no WhatsApp/Telegram MCP entries. |
| No real credentials committed | PASS | Broad scan found env names, placeholders, docs, and tests; no real credential values observed. |

## Secret Redaction

| Check | Result | Notes |
| --- | --- | --- |
| Raw WhatsApp tokens never returned | PASS | Direct provider status and invocation error tests cover fake configured token values. |
| Raw Telegram bot tokens never returned | PASS | Direct provider status and invocation error tests cover fake configured token values. |
| OAuth/API tokens never displayed after save | PARTIAL | Saved MCP values are redacted by configured field names, but MCP discovery errors may leak arbitrary configured values. See blocker B1. |
| Logs/errors/status responses redact token-like values | PARTIAL | Marker-based redaction works for text containing marker words; arbitrary configured MCP secret values are not replaced. |
| Nested keys containing token/secret/password/credential/authorization/api_key redacted | PASS | Key-based nested redaction exists in MCP/direct redaction helpers. |

## Provider Architecture

| Check | Result | Notes |
| --- | --- | --- |
| Gmail remains MCP | PASS | `gmail` remains in the MCP provider defaults and provider config definitions. |
| Google Calendar remains MCP | PASS | `google_calendar` remains MCP. |
| Tavily/DuckDuckGo Search remains MCP | PASS | `search_tavily` and `search_duckduckgo` remain MCP. |
| WhatsApp remains direct API only | PASS | `whatsapp_api` appears as `external_api`; stale MCP entries are ignored. |
| Telegram remains direct Bot API only | PASS | `telegram_bot_api` appears as `external_api`; stale MCP entries are ignored. |
| WhatsApp/Telegram do not appear in MCP discovery | PASS | Tests cover stale MCP config entries being skipped. |
| WhatsApp/Telegram direct tools remain outside `mcp_tools` | PASS | Tests assert direct tool names are in `external_api_tools`, not `mcp_tools`. |

## Frontend Behavior

| Check | Result | Notes |
| --- | --- | --- |
| Tools Ops shows provider config inputs safely | PASS | `ToolsOpsCockpit.jsx` loads `/api/config/providers` and renders field definitions. |
| Saved secrets displayed only as redacted/configured | PASS | Secret fields use password inputs and placeholder text; saved secret display depends on redacted API values. |
| Direct API providers use Validate Status | PASS | Direct rows call external provider status rather than MCP discovery. |
| MCP providers use Refresh Metadata/discovery | PASS | MCP rows call MCP discovery refresh. |
| Frontend does not retain secrets after successful save longer than needed | PASS | Successful save clears the provider draft state and reloads redacted status. |
| Frontend config rendering covered by tests | CAVEAT | Backend API tests cover config behavior, but no dedicated frontend test currently asserts the Provider Configuration form renders or protects secret placeholders. |

## Blockers

### B1. MCP validation/status can leak arbitrary configured MCP secret values in discovery errors

Source references:

- `src/tools/mcp_provider_config.py:144-152` redacts discovery error text only when the text contains marker words such as `api_key`, `token`, `secret`, `password`, `credential`, or `authorization`.
- `src/tools/mcp_provider_config.py:94-107` includes `last_error` in provider status output.
- `src/tools/provider_config.py:358-369` returns MCP validation status and nested status from `get_mcp_provider_status(..., refresh=True, include_config=False)`.

Additional review check performed with a fake MCP config value and a mocked discovery exception showed that an exception string containing the configured value without a marker word is returned as `last_error`.

Impact: after real Gmail, Google Calendar, or Tavily/DuckDuckGo credentials are entered, a provider/transport/client failure that echoes a credential-like value could surface that value through validation/status APIs and the frontend.

Required fix before real MCP onboarding:

- Redact configured MCP secret values, not only secret-looking keys or messages.
- Apply this before storing/returning `last_error` from MCP discovery/status.
- Include nested MCP config secret fields such as `env.*`, `oauth.clientSecret`, access tokens, refresh tokens, and any field whose key matches secret markers.
- Add a regression test with a fake configured MCP secret value that does not contain marker words and assert it is absent from `/api/config/providers/{provider_id}/validate` and MCP provider status responses.

## Caveats

### C1. Frontend provider config rendering lacks a focused test

The frontend build passes, and the component code is wired to `/api/config/providers`, but the current requested test set does not include a focused assertion that the Provider Configuration panel renders the expected fields, redacted placeholders, save/validate/clear controls, and no raw saved secret text.

### C2. `.env` writes normalize the file and drop comments/order

`src/tools/provider_config.py` rewrites `.env` from parsed key/value pairs. It preserves values, but comments, blank lines, and original ordering are not preserved. This is not a credential leak, but it is an operator-experience caveat.

## Test Results

Command:

```powershell
python -m pytest tests/test_api_server.py tests/test_frontend_api.py tests/test_tools_t6_mcp_api.py tests/test_tools_t8_policy_classification.py tests/test_tools_t9_observability_api.py -q
```

Result:

```text
35 passed, 1 warning
```

Note: LangSmith emitted a masked telemetry connection warning after pytest completed. It did not fail the test command.

Frontend build:

```powershell
cd frontend
npm run build
cd ..
```

Result: passed.

## Static Scan Results

`git status --short` showed expected provider onboarding changes and new docs/templates.

`git diff -- . ':!*.env'` showed no real secrets. It showed the new config routes, Tools Ops provider configuration UI, `.gitignore` template allowances, and provider-config tests.

Broad scan:

```powershell
rg -n "WHATSAPP_API_TOKEN|TELEGRAM_BOT_TOKEN|GMAIL|GOOGLE|TAVILY|DUCKDUCKGO|api_key|secret|token" . --glob '!node_modules' --glob '!frontend/dist'
```

Interpretation: hits are environment variable names, placeholders, docs, tests, package metadata, and redaction code. No real committed credential value was observed. Historical/planning docs still mention old states, which is acceptable as historical material.

Removed endpoint scan: no `/api/browser` or `/api/github` calls in frontend source; remaining hits are tests asserting removal.

## Recommendation

Do not enter real MCP credentials yet. Fix blocker B1 first, then rerun this review.

After B1 is fixed, it should be safe to enter real credentials locally for validation-only onboarding, assuming real sends/writes remain behind HITL and manual smoke tests use safe test accounts/environments.
