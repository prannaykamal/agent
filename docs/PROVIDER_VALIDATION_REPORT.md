# Provider Validation Report

## Current Status

This report documents the provider onboarding surface after adding frontend-safe configuration APIs.

## Provider Classification

MCP providers:

- Gmail MCP: `gmail`
- Google Calendar MCP: `google_calendar`
- Tavily Search MCP: `search_tavily`
- DuckDuckGo Search MCP: `search_duckduckgo`

Direct API providers:

- WhatsApp API: `whatsapp_api`
- Telegram Bot API: `telegram_bot_api`

WhatsApp and Telegram are intentionally not MCP providers.

## Validation Behavior

- `POST /api/config/providers/{provider_id}/validate` performs status/discovery-only validation.
- MCP validation may run safe `tools/list` through the MCP boundary when supported.
- WhatsApp/Telegram validation checks local configuration/status only and never sends messages.
- Send actions remain governed by HITL approval.

## Secret Handling

- Raw secrets are accepted only through configuration writes.
- Raw secrets are stored only in ignored local files such as `.env` or `.agent/mcp_config.json`.
- API responses return `[REDACTED]` for secret fields.
- Direct provider error text redacts configured WhatsApp/Telegram token values.

## Automated Verification

Latest focused run:

```text
python -m pytest tests/test_api_server.py tests/test_frontend_api.py tests/test_tools_t6_mcp_api.py tests/test_tools_t8_policy_classification.py tests/test_tools_t9_observability_api.py -q
```

Run this after provider config changes and before real onboarding.

## Manual Validation Still Required

Real credentials and provider smoke tests are still required for:

- Gmail MCP
- Google Calendar MCP
- Tavily/DuckDuckGo Search MCP
- WhatsApp API
- Telegram Bot API

Manual validation must use safe accounts/environments and must not bypass HITL for sends or writes.
