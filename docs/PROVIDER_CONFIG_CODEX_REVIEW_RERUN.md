# Provider Config Codex Review Rerun

## Verdict

APPROVED WITH CAVEATS

The previous MCP configured-secret redaction blocker is fixed. It is now safe to enter real provider credentials locally for validation/onboarding, assuming credentials are entered only into ignored local files or through the redacted config API and real write/send actions remain behind HITL.

## Previous Blocker Status

| Previous blocker | Status | Evidence |
| --- | --- | --- |
| MCP validation/status errors could leak arbitrary configured MCP secret values when exception text did not contain marker words | FIXED | `src/tools/mcp_provider_config.py` now collects configured MCP redaction values from credential-bearing config blocks and applies them in discovery/status serialization, config API redaction, bridge warnings, and invocation errors. |

## MCP Configured-Value Redaction

Reviewed implementation:

- `src/tools/mcp_provider_config.py` defines marker keys including `token`, `secret`, `password`, `credential`, `authorization`, `api_key`, `access_key`, `access_token`, and `refresh_token`.
- `collect_mcp_secret_values()` collects redaction targets from MCP config values under secret-keyed fields and credential-bearing containers such as `env`, `headers`, and `oauth`.
- Empty, very short, and placeholder-like values are ignored to reduce accidental broad redaction.
- `redact_observability_text()` replaces configured secret values before marker-based redaction and truncation.
- `MCPProviderConfig.with_discovery()` stores sanitized `last_error` values.
- `MCPProviderConfig.to_status_dict()` re-sanitizes `last_error`, `env`, and `url` before serialization.

Additional no-write probe performed during review:

- URL-like string containing `gmail_plain_value_ABC123_NO_MARKER`: redacted and surrounding URL context preserved.
- Header-like string containing the fake value: redacted; because `Authorization` is a marker, the full header text is replaced with `[REDACTED]`.
- Nested dict/list payload containing the fake value: redacted recursively while unrelated safe values were preserved.

## Protected Paths

| Path | Result | Notes |
| --- | --- | --- |
| `/api/config/providers` | PASS | Provider config status sanitizes nested MCP status and saved values. |
| `/api/config/providers/{provider_id}/validate` | PASS | MCP validation uses provider status/discovery and returns sanitized errors/status. |
| `/api/tools/mcp/providers` | PASS | Status serialization applies provider redaction values. |
| `/api/tools/mcp/providers/{provider_id}` | PASS | Detail responses use the same status serialization. |
| MCP discovery refresh responses | PASS | Refresh returns MCP provider status dicts after sanitized discovery. |
| MCP bridge warnings/errors | PASS | `src/mcp_gateway/mcp_bridge.py` redacts warning text using the server config before printing. |
| MCP invocation errors | PASS | `src/tools/mcp_invocation.py` redacts `tools/call` exception text using provider redaction values. |
| Observability/status response previews | PASS | Tools observability consumes the sanitized provider status output and applies its own redaction layer. |

## Provider Architecture

| Provider | Expected | Result |
| --- | --- | --- |
| Gmail | MCP | PASS |
| Google Calendar | MCP | PASS |
| Tavily/DuckDuckGo Search | MCP | PASS |
| WhatsApp | Direct API only | PASS |
| Telegram | Direct Bot API only | PASS |

WhatsApp and Telegram are not in the MCP provider defaults, MCP provider status, or MCP discovery allowlist. Direct WhatsApp/Telegram tools remain outside `/api/tools.mcp_tools` and in the direct/external API bucket.

## Secret Examples and Git Safety

| Check | Result | Notes |
| --- | --- | --- |
| `.env.example` contains no real secrets | PASS | Placeholder values only. |
| `.agent/mcp_config.example.json` contains no real secrets | PASS | Disabled placeholder MCP configs only. |
| `.gitignore` ignores real `.env` | PASS | `.env` and `.env.*` are ignored except `.env.example`. |
| Runtime `.agent/*` config ignored | PASS | `.agent/*` ignored except `.agent/mcp_config.example.json`. |
| No real credentials in git diff | PASS | Review of `git diff -- . ':!*.env'` showed config/API/test/docs changes and placeholders only. |

## Regression Tests

Requested test command:

```powershell
python -m pytest tests/test_api_server.py tests/test_frontend_api.py tests/test_tools_t6_mcp_api.py tests/test_tools_t8_policy_classification.py tests/test_tools_t9_observability_api.py -q
```

Result:

```text
38 passed, 1 warning
```

Notes:

- The warning is the existing Starlette/httpx deprecation warning.
- LangSmith emitted a masked external telemetry upload warning after pytest completed; it did not fail the local tests.

Coverage confirmed in `tests/test_tools_t6_mcp_api.py`:

- marker-free fake Gmail MCP secret redaction
- marker-free fake Calendar MCP secret redaction
- marker-free fake Search MCP secret redaction
- provider config validation redaction
- MCP provider status redaction
- bridge warning redaction
- invocation error redaction
- WhatsApp/Telegram direct API redaction still passing
- WhatsApp/Telegram remain direct API providers and are excluded from MCP status/tool buckets

## Frontend Build

Command:

```powershell
cd frontend
npm run build
cd ..
```

Result: passed.

## Static Scan

Command:

```powershell
rg -n "gmail_plain_value_ABC123_NO_MARKER|calendar_plain_value_ABC123_NO_MARKER|search_plain_value_ABC123_NO_MARKER" . --glob '!node_modules' --glob '!frontend/dist'
```

Result: fake marker-free values appear only in `tests/test_tools_t6_mcp_api.py`, where they are defined for regression coverage.

## Remaining Caveats

1. The redactor intentionally collects all scalar values from MCP `env`, `headers`, and `oauth` blocks. This is conservative and may over-redact non-secret but long values from those blocks if they appear in errors. That is acceptable for credential safety.
2. URL/header/nested dict/list handling was verified by code inspection and a no-write review probe. The committed tests cover discovery/status/invocation paths with marker-free values, but do not separately name URL/header/nested variants as standalone test cases.
3. Frontend Provider Configuration rendering still lacks a dedicated component-level test, though the component is wired and production build passes.

## Recommendation

Safe to enter real provider credentials locally: YES, with the caveats above.

Use local `.env` for WhatsApp/Telegram direct API credentials and local `.agent/mcp_config.json` for Gmail, Google Calendar, and Search MCP configuration. Do not commit those runtime files. Keep real sends/writes behind HITL and use safe test accounts/environments for manual onboarding smoke tests.
