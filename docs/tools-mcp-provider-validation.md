# Tools MCP Provider Validation

This document records the Phase T0 manual validation checklist for the target provider-managed MCP tools.

Phase T0 does not implement MCP provider wiring and does not change runtime behavior.

## Core Rule

MCP tools are provider-managed. Local code must not reimplement provider behavior for Tavily, DuckDuckGo, Google Calendar, WhatsApp, Telegram, or Gmail.

Local code may manage only:

- provider discovery
- MCP registration
- tool metadata exposure
- routing
- permission and HITL policy
- invocation boundaries
- error handling
- observability
- frontend status display

## Current MCP Config State

The current `.agent/mcp_config.json` does not configure the target provider set. It currently contains:

- `filesystem`
  - transport: `stdio`
  - command: `python`
  - args: `["-m", "mcp.server.filesystem", "./.agent/scratch"]`
- `fetch_sse`
  - transport: `sse`
  - url: `http://localhost:8000/sse`

These entries are useful as current-state examples only. They do not validate Tavily/DuckDuckGo, Google Calendar, WhatsApp, Telegram, or Gmail MCP availability.

## Missing Target Provider Configs

The following target providers are not validated in the current config:

- Tavily / DuckDuckGo Search MCP
- Google Calendar MCP
- WhatsApp MCP
- Telegram MCP
- Gmail MCP

Before implementation phases replace local adapters, each provider must be manually validated with safe credentials and a safe test account/environment.


## Phase T6 Provider Status Foundation

Phase T6 adds a local provider-managed MCP discovery and status boundary without replacing the legacy local adapters. The target providers are represented by stable provider IDs:

- `search_tavily`
- `search_duckduckgo`
- `google_calendar`
- `whatsapp`
- `telegram`
- `gmail`

The local system now treats missing target provider configuration as an unavailable, non-fatal state. App startup, `/api/tools`, chat, Personal OS, cron, and memory workers must continue when these providers are not configured.

Read-only status endpoints:

- `GET /api/tools/mcp/providers`
- `GET /api/tools/mcp/providers/{provider_id}`
- `POST /api/tools/mcp/providers/{provider_id}/discover` for explicit metadata refresh only

The status layer exposes provider IDs, display names, enabled/configured state, transport type, credential status, discovery status, availability status, expected tool hints, discovery timestamps, redacted errors, and discovered provider-managed tool metadata when available. It must not expose secrets or raw credentials.

Discovery rules:

- Load target entries from `.agent/mcp_config.json` only.
- Connect through MCP transports only (`stdio` and `sse` are currently discoverable by the local bridge; `http`, `app_connector`, and `unknown` require manual/provider validation until supported safely).
- Call MCP `tools/list` only during explicit discovery/refresh flows in code or tests.
- Normalize discovered MCP tools into provider-managed `ToolMetadata`.
- Mark failed providers unavailable without affecting other providers.
- Do not call provider action tools such as send/create/update/delete during discovery.

T6 still requires manual validation for real providers because no real Tavily, DuckDuckGo, Google Calendar, WhatsApp, Telegram, or Gmail MCP server is configured in the current workspace.


## Phase T7 Provider Adapter Replacement

Phase T7 replaces local provider behavior for search, Google Calendar, Gmail, WhatsApp, and Telegram with provider-managed MCP invocation boundaries. Compatibility wrappers such as `search_web`, `calendar_create_event`, `email_send`, `whatsapp_send`, and `telegram_send` may remain, but they must invoke MCP `tools/call` only.

Removed local provider behaviors:

- Tavily REST and DuckDuckGo library fallback from the local search path.
- Google Calendar REST/local SQLite CRUD as provider source of truth.
- SMTP/IMAP Gmail behavior.
- WhatsApp Graph REST/local message table source-of-truth behavior.
- Telegram Bot REST/local message table source-of-truth behavior.

Legacy tables (`calendar_events`, `emails`, `whatsapp_messages`, `telegram_messages`) are retained temporarily for compatibility/history, but T7 wrappers must not treat them as provider source of truth and must not write provider actions into them.

If a target MCP provider or capability is unavailable, the local system returns a safe unavailable result. It must not silently fall back to the removed local provider implementation.

## Provider Checklist Template

For each provider, validate:

- provider/server availability
- transport type: `stdio`, `SSE`, `HTTP`, app connector, or unknown
- credential model
- required environment variables or connector auth flow
- exact MCP server config entry
- tool names returned by `tools/list`
- tool input schemas
- tool output shape
- read/write capabilities
- provider confirmation behavior
- provider error behavior when credentials are missing
- safe smoke-test account/environment
- whether local HITL approval is needed before invocation
- whether provider-managed confirmation is also required

## Tavily / DuckDuckGo Search MCP

Manual validation required:

- Confirm whether Tavily, DuckDuckGo, or both are available as MCP providers.
- Confirm transport type.
- Confirm credential model.
- Confirm search tool names and input schema.
- Confirm max results, safe search, region, and freshness parameters if exposed.
- Confirm provider unavailable behavior.
- Run a safe read-only smoke query.

Expected policy:

- General search is read-only and normally needs no HITL approval.
- Queries containing private/sensitive data may require confirmation or local policy warning.

Local code must not call Tavily REST or DuckDuckGo libraries directly in the final architecture.

## Google Calendar MCP

Manual validation required:

- Confirm MCP provider/server availability.
- Confirm OAuth or credential model.
- Confirm required calendar scopes.
- Confirm read, create, update, delete, availability, and conflict-related tool names if available.
- Confirm schemas for event timestamps, attendees, recurrence, location, and calendar ID.
- Confirm provider confirmation behavior.
- Use a safe test calendar for smoke tests.

Expected policy:

- Calendar read: no approval needed.
- Calendar create/update/delete: HITL approval required.
- Any attendee invitation or external guest modification: HITL approval required.

Local code must not implement Google Calendar CRUD or direct Google Calendar REST calls in the final architecture.

## WhatsApp MCP

Manual validation required:

- Confirm MCP provider/server availability.
- Confirm account/phone identity model.
- Confirm transport type and credentials.
- Confirm read/send tool names.
- Confirm message schema and delivery status behavior.
- Confirm provider confirmation behavior.
- Use a safe test recipient/environment.

Expected policy:

- Read: no approval or confirmation recommended depending privacy scope.
- Send: HITL approval required with recipient and message preview.

Local code must not call Meta Graph WhatsApp APIs directly in the final architecture.

## Telegram MCP

Manual validation required:

- Confirm MCP provider/server availability.
- Confirm bot versus user account mode.
- Confirm transport type and credentials.
- Confirm read/send tool names.
- Confirm chat ID or recipient resolution behavior.
- Confirm provider confirmation behavior.
- Use a safe test chat.

Expected policy:

- Read: no approval or confirmation recommended depending privacy scope.
- Send: HITL approval required with chat and message preview.

Local code must not call Telegram Bot API directly in the final architecture.

## Gmail MCP

Manual validation required:

- Confirm MCP provider/server availability.
- Confirm OAuth or credential model.
- Confirm required Gmail scopes.
- Confirm read, search, draft, send, thread, label, archive, and delete tool names if exposed.
- Confirm tool schemas and body/attachment behavior.
- Confirm provider confirmation behavior.
- Use a safe test Gmail account.

Expected policy:

- Read/search: no approval, or confirmation recommended for broad/private queries.
- Draft: confirmation recommended.
- Send: HITL approval required.
- Delete/archive/label modifications: approval or confirmation depending impact.

Local code must not use SMTP or IMAP adapters for Gmail provider behavior in the final architecture.

## Validation Evidence to Capture Later

For each provider, capture:

- provider ID
- transport type
- sanitized config shape
- discovered tool names
- schema summary
- unavailable-state result
- safe read-only smoke-test result
- safe write-test result only after HITL approval
- known limitations

Do not record secrets, tokens, OAuth refresh tokens, API keys, raw message bodies, or hidden reasoning in this document.

