# Tools Security Policy

Tool execution is controlled by centralized policy, HITL approval, and a single invocation boundary.

## Policy Outcomes

- `no_approval_needed`
- `confirmation_recommended`
- `approval_required`
- `blocked`
- `provider_managed_confirmation`
- `unavailable`

## Tool Classes

| Tool class | Default policy |
| --- | --- |
| Web search read | no approval needed |
| Sensitive web search query | confirmation recommended when detectable |
| Calendar read/list/availability | no approval needed |
| Calendar create/update/delete/invite | approval required |
| Gmail read/search | no approval needed or confirmation recommended depending scope |
| Gmail draft | confirmation recommended |
| Gmail send/delete/archive/label write | approval required |
| WhatsApp read | no approval needed or confirmation recommended depending scope |
| WhatsApp send | approval required |
| Telegram read | no approval needed or confirmation recommended depending scope |
| Telegram send | approval required |
| Personal OS read/status/list/heartbeat | no approval needed |
| Personal OS bounded local write | policy-known; confirmation recommended or approval required by impact |
| Personal OS sub-agent lifecycle write | approval required unless explicitly low-impact |
| Personal OS destructive action | approval required or blocked |
| Cron create/update/delete for read action | no approval or confirmation recommended |
| Cron create/update/delete for write/external/destructive action | approval required |
| Cron-triggered write/external/destructive action | approval required unless durable preapproval is explicitly implemented |
| Removed browser/code sandbox tool | blocked |

## Primary and Secondary Boundaries

The primary user-facing agent may bind available, enabled tools from the unified registry. Secondary memory LLM paths must not bind or invoke user-facing tools.

Memory workers can call secondary LLMs for memory tasks, but they cannot use Personal OS, cron, or MCP provider tools.

## Approval Preview Rules

Approval previews should show:

- tool name and provider
- action type
- recipient/calendar/resource target where relevant
- redacted argument preview
- risk class and reason
- scheduled run context when relevant

Approval previews must not show:

- secrets
- tokens
- OAuth credentials
- full email/message bodies unless explicitly safe and required
- provider raw payloads
- hidden reasoning
- scratchpads
- chain-of-thought

## Approval Resume Safety

Approval resume must revalidate:

- tool metadata exists
- tool is not removed
- provider is available for MCP tools
- policy still permits execution
- approval has not already executed
- arguments remain valid
- scheduled run is still pending or waiting as expected

If validation fails, execution is blocked or marked unavailable.

## Removed Tools

The removed browser/code sandbox names always classify as blocked:

- `safe_browse_url`
- `capture_screenshot`
- `run_code`
- `github_clone`
- `github_commit_and_push`
- `github_merge`

Old approval requests for these names cannot execute.

## Observability Redaction

Tools observability is read-only and redacts credential-like keys, raw provider payloads, message bodies, hidden reasoning, scratchpads, and chain-of-thought. It preserves IDs, status, timestamps, counts, provider IDs, risk class, approval policy, and redacted previews.
