# Tools Architecture

This document describes the final tools architecture after the T0-T10 tools migration.

## Taxonomy

The system has three tool classes:

- Local non-MCP tools: bounded Personal OS actions and the local cron scheduler.
- Provider-managed MCP tools: Tavily or DuckDuckGo Search, Google Calendar, Gmail, WhatsApp, and Telegram.
- Removed tools: browser sandbox and code/GitHub sandbox tools.

MCP providers own provider behavior. Local code discovers, registers, policy-gates, invokes through MCP, observes, and reports errors. It does not implement provider-specific search, calendar, mail, WhatsApp, or Telegram behavior locally.

## Local Tools

Personal OS is the bounded local operations layer. It owns local tasks, local agent lifecycle metadata, checkpoint metadata, local locks, local health/status, audit, and idempotency. It may read memory through approved retrieval or repository boundaries, but it must not write semantic, episodic, or procedural memory tables directly.

Cron is the durable local scheduler. It owns schedule definitions and run attempts in scheduler tables. It is separate from `memory_jobs`, which remains dedicated to memory background processing.

## Provider-Managed MCP Tools

Target MCP providers are represented by stable provider IDs:

- `search_tavily`
- `search_duckduckgo`
- `google_calendar`
- `gmail`
- `whatsapp`
- `telegram`

Provider discovery loads `.agent/mcp_config.json`, connects only through MCP transports, calls `tools/list`, and normalizes returned schemas into registry metadata. Invocation uses MCP `tools/call` only.

If a provider is not configured, fails discovery, or lacks a requested capability, the local system returns a safe unavailable result. It does not fall back to old local provider adapters.

## Registry and Routing

The unified registry separates:

- `implementation_type = local`
- `implementation_type = mcp`
- `implementation_type = removed`

Bindable tools are enabled, available, and not removed. Removed tools remain visible only as blocked metadata for policy and observability.

The primary chat graph may bind user-facing tools from the bindable registry. Secondary memory LLM and memory worker paths must not bind or invoke user-facing tools.

## Policy and HITL

Tool policy is centralized in the tools policy service. It evaluates tool metadata, caller source, arguments, availability, and approval context.

Policy outcomes are:

- no approval needed
- confirmation recommended
- approval required
- blocked
- provider managed confirmation
- unavailable

High-risk writes, destructive actions, external sends, and unsafe scheduled actions require HITL approval. Approval resume revalidates tool existence, provider availability, current policy, arguments, and scheduled run state before execution.

## Invocation and Audit

All tool execution flows through the unified invocation boundary or the MCP invocation boundary. The boundary rejects removed and unavailable tools, evaluates policy, creates or respects HITL approval when appropriate, normalizes errors, and records safe audit/tool-call records where existing infrastructure supports it.

Audit records must be redacted. Secrets, raw provider payloads, hidden reasoning, scratchpads, and chain-of-thought fields are not stored or exposed.

## Observability

Tools observability is read-only. It exposes registry health, provider status, policy metadata, Personal OS status, cron schedules and runs, recent tool calls/results, audit rows, and blocked attempts. Observability endpoints do not invoke tools, refresh providers implicitly, create approvals, execute schedules, or mutate state.

## Removed Sandbox Proof

The browser sandbox and code/GitHub sandbox are removed from runtime behavior. They are not bindable, not exposed as active tools, and their old API routes are not supported. Any remaining references should be historical docs or tests that assert removal.

Removed tool names:

- `safe_browse_url`
- `capture_screenshot`
- `run_code`
- `github_clone`
- `github_commit_and_push`
- `github_merge`

## Memory Boundary

The completed memory architecture remains separate:

- chat retrieval uses Phase 9B context assembly
- memory writes use approved memory repositories and background jobs
- secondary LLM is restricted to memory worker paths
- tools do not bypass semantic deduplication, episodic stores, procedural approval, or memory observability boundaries

## Acceptance Checklist

- Removed sandbox tools are absent from active runtime surfaces.
- Provider-managed MCP tools are discovered and invoked only through MCP protocol boundaries.
- Local duplicate provider implementations are not active.
- Personal OS is bounded and local.
- Cron uses durable schedule/run tables, not `memory_jobs`.
- High-risk actions require HITL.
- Approval resume fails closed when state changes.
- Observability is read-only and redacted.
- Real provider validation remains manual until safe MCP servers and accounts are configured.
