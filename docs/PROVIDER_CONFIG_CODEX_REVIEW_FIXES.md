# Provider Config Codex Review Fixes

## Summary

This note records the fix for the MCP config/error redaction blocker from `docs/PROVIDER_CONFIG_CODEX_REVIEW.md`.

The previous review found that MCP discovery/status errors could leak an actual configured secret value when an exception echoed the value without a marker word such as `token`, `secret`, or `authorization`.

## Fix

MCP redaction now handles both:

- marker-based secret keys, including token, secret, password, credential, authorization, api_key, access_key, access_token, and refresh_token
- actual configured MCP secret values collected from local MCP configuration blocks

Configured redaction values are collected only for redaction and are never returned or logged raw.

## Protected Paths

The fix covers:

- MCP provider discovery errors
- MCP provider status serialization
- `/api/config/providers`
- `/api/config/providers/{provider_id}/validate`
- `/api/tools/mcp/providers`
- `/api/tools/mcp/providers/{provider_id}`
- MCP discovery refresh responses
- MCP bridge warning output
- MCP tools/call invocation errors
- tools observability provider status responses

## Regression Coverage

Added regression tests simulate marker-free MCP secret values in Gmail, Google Calendar, and Search provider configs and assert those values do not appear in config API responses, validation responses, provider status responses, observability responses, MCP bridge warnings, or MCP invocation errors.

Existing WhatsApp/Telegram direct API redaction tests continue to pass. WhatsApp and Telegram remain direct API providers only; Gmail, Google Calendar, and Tavily/DuckDuckGo Search remain MCP providers.

## Verification

Focused and requested regression tests passed after the fix. Frontend production build also passed.

No real credentials were added, and no real provider sends or writes were executed.
