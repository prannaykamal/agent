# Tools Operator Runbook

This runbook covers safe operation of the final tools architecture.

## Start Services

Backend:

```powershell
python src/api/server.py
```

Frontend development server:

```powershell
cd frontend
npm run dev
```

Frontend production build:

```powershell
cd frontend
npm run build
```

Explicit scheduler worker loop:

```powershell
python -m src.background_worker
```

Workers are not auto-started by chat or API requests.

## Check Tool Health

Use these read-only endpoints:

- `GET /api/tools/status`
- `GET /api/tools/observability/overview`
- `GET /api/tools/mcp/providers`
- `GET /api/tools/personal-os/status`
- `GET /api/tools/cron/schedules`
- `GET /api/tools/cron/runs`

Provider status values of `not_configured`, `failed`, or `unavailable` are safe states. They should not crash chat, API startup, Personal OS, cron, or memory workers.

## Inspect MCP Providers

1. Confirm `.agent/mcp_config.json` contains the intended provider entry.
2. Confirm the transport is `stdio`, `sse`, or another explicitly supported/provider-managed transport.
3. Run `GET /api/tools/mcp/providers`.
4. Optionally run explicit discovery for one provider if enabled by the API.
5. Confirm discovered tool names and schemas.
6. Run read-only smoke tests first.
7. Run write/send smoke tests only through HITL approval and safe test accounts.

Do not add local fallback calls to provider REST, SMTP, IMAP, or SDKs when MCP is unavailable.

## Use Cron Safely

Cron is for local scheduled assistant actions. Google Calendar MCP is for calendar events and is not a cron replacement.

Inspect schedules:

- `GET /api/tools/cron/schedules`
- `GET /api/tools/cron/runs`

Rules:

- Read-only local scheduled actions may execute directly when policy permits.
- Local write actions are policy-gated.
- External communication and high-risk scheduled actions require HITL approval unless a future durable preapproval model is explicitly implemented.
- `memory_jobs` is not used as the schedule definition table.

## Review Approvals

Approval previews should include enough target, action, and argument preview information for a human to decide safely. They must not include secrets, full provider payloads, hidden reasoning, scratchpads, or chain-of-thought.

Approval resume revalidates:

- tool still exists
- tool is not removed
- provider is available
- policy still permits execution
- arguments remain valid
- scheduled run state remains eligible

If any check fails, the result must fail closed.

## Personal OS Operations

Personal OS is local only. It may manage local tasks, checkpoints, locks, local agent lifecycle metadata, and status. It must not send Gmail, WhatsApp, Telegram, Calendar, or search provider requests directly.

Inspect:

- `GET /api/tools/personal-os/status`
- `GET /api/tools/personal-os/actions`
- `GET /api/tools/personal-os/audit`

## Troubleshooting

Provider unavailable:

- Check provider config.
- Check credentials in the provider-managed MCP server, not local fallback code.
- Confirm `tools/list` succeeds.
- Keep write smoke tests disabled until read-only discovery succeeds.

Approval stuck:

- Inspect approval request status.
- Inspect tool/provider status.
- Confirm approval resume did not fail closed because provider availability changed.

Cron missed run:

- Inspect `tool_schedules.next_run_at`, `last_run_at`, and missed-run policy.
- Inspect `tool_schedule_runs`.
- Confirm scheduler worker was explicitly running.

Blocked removed tool:

- Expected for old browser/code sandbox approvals or tool calls.
- Do not attempt to re-enable removed sandbox routes.

## Backup

Back up the SQLite database and `.agent/skills` together. MCP provider credentials should be backed up through the provider-managed credential system, not copied into docs or logs.
