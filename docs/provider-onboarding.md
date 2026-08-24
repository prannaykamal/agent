# Provider Onboarding

## Provider Model

Ivo separates providers into three groups:

- MCP providers: Gmail, Google Calendar, Tavily Search, DuckDuckGo Search.
- Direct API providers: WhatsApp API and Telegram Bot API.
- Local tools: Personal OS and cron remain local and are not configured as external providers.

WhatsApp and Telegram are not MCP providers. They must not appear in MCP discovery or MCP provider status.

## Configuration APIs

### `GET /api/config/providers`

Returns frontend-safe provider configuration status. The response includes:

- `provider_id`
- `display_name`
- `provider_type` as `mcp` or `external_api`
- field definitions
- configured/missing state
- redacted saved values
- validation status
- redacted validation error

Raw secret values are never returned.

### `POST /api/config/providers/{provider_id}`

Updates local provider configuration from a JSON body:

```json
{
  "values": {
    "enabled": true,
    "transport_type": "stdio"
  }
}
```

MCP providers are written to `.agent/mcp_config.json`. Direct API providers are written to local `.env` and applied to the current process environment for immediate status validation. The response is redacted.

### `DELETE /api/config/providers/{provider_id}/secret`

Clears stored secret fields for that provider. Optional query parameter:

- `field_name`: clear one secret field only

The response is redacted.

### `POST /api/config/providers/{provider_id}/validate`

Runs safe validation only:

- MCP providers: config/status and safe MCP discovery where supported.
- Direct API providers: local configuration/status check only.

This endpoint does not send WhatsApp/Telegram messages and does not perform external write actions.

## MCP Provider Onboarding

Use `.agent/mcp_config.json` for real local config and `.agent/mcp_config.example.json` as the tracked template.

Allowed MCP providers:

- `search_tavily`
- `search_duckduckgo`
- `google_calendar`
- `gmail`

Stale `whatsapp` and `telegram` MCP entries are ignored by the MCP bridge.

## Direct API Provider Onboarding

Use `.env` for real local secrets and `.env.example` as the tracked template.

WhatsApp API fields:

- `WHATSAPP_API_TOKEN`
- `WHATSAPP_PHONE_NUMBER_ID`
- `WHATSAPP_API_VERSION`
- `WHATSAPP_API_BASE_URL`

Telegram Bot API fields:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_TEST_CHAT_ID`
- `TELEGRAM_API_BASE_URL`

Send actions require HITL approval and are not executed by validation.

## Safety Rules

- Do not commit `.env` or `.agent/mcp_config.json` with real secrets.
- Do not expose raw tokens in API responses or frontend state.
- Do not run real sends during validation.
- Use safe test accounts/chats when onboarding real providers.
