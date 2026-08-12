# MCP Wiring Guide

MCP providers are provider-managed. The local assistant does not implement Tavily, DuckDuckGo, Google Calendar, or Gmail behavior. WhatsApp and Telegram are intentionally not MCP providers; they use direct API provider boundaries documented in the tools architecture and security policy.

## Local Responsibilities

The local system handles:

- provider config loading
- provider discovery
- `tools/list` schema normalization
- registry metadata
- policy and HITL enforcement
- `tools/call` invocation boundary
- safe unavailable results
- observability and redaction

## Provider Responsibilities

The MCP provider/server handles:

- authentication
- provider API calls
- provider-specific data models
- provider send/create/update/delete behavior
- provider-side confirmations where applicable
- provider-specific error details

## Config Shape

Target provider IDs:

- `search_tavily`
- `search_duckduckgo`
- `google_calendar`
- `gmail`

Example sanitized `.agent/mcp_config.json` shape:

```json
{
  "mcpServers": {
    "gmail": {
      "transport": "stdio",
      "command": "provider-managed-gmail-mcp",
      "args": [],
      "env": {
        "PROVIDER_SECRET": "set outside committed files"
      }
    }
  }
}
```

Do not commit secrets. Status APIs redact environment values and credential-like fields.

## Discovery

Discovery should:

1. Load target provider config.
2. Connect by MCP transport.
3. Call `tools/list`.
4. Normalize each tool into registry metadata.
5. Mark the provider unavailable on failure.
6. Avoid any provider action invocation.

Discovery must not call send, create, update, delete, search, calendar, or email provider APIs directly. WhatsApp and Telegram are outside MCP discovery and must not appear in MCP provider refresh flows.

## Invocation

Invocation should:

1. Look up provider and tool metadata.
2. Validate arguments against the MCP input schema where available.
3. Evaluate centralized policy.
4. Create or require HITL approval when policy demands it.
5. Invoke MCP `tools/call` only after policy allows execution.
6. Normalize success or unavailable/error results.

No local REST, SMTP, IMAP, SDK, or library fallback is permitted.

## Manual Validation Checklist

For each provider:

- provider/server installed and reachable
- transport type known
- safe test account configured
- credential model understood
- `tools/list` returns expected tools
- schemas match local policy expectations
- read-only smoke test passes
- write/send smoke test passes only after HITL approval
- provider unavailable behavior is safe
- provider errors are redacted in observability

Manual validation status must remain explicit. Automated mocked tests do not prove real provider availability.


## WhatsApp / Telegram Direct API Note

WhatsApp API and Telegram Bot API were intentionally removed from the MCP provider list. They are reported by direct external API provider status endpoints and do not participate in MCP `tools/list` or `tools/call`. Their send actions remain HITL approval-required.
