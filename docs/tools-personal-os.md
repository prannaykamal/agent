# Personal OS

Personal OS is the bounded local non-MCP operations layer.

## Responsibilities

Personal OS owns:

- local task state
- local status and readiness
- local sub-agent lifecycle metadata and control
- checkpoint metadata for HITL recovery
- local resource locks
- local audit and idempotency for supported writes
- references to approved procedural skills when needed

## Non-Responsibilities

Personal OS must not:

- call Gmail, WhatsApp, Telegram, Google Calendar, Tavily, or DuckDuckGo directly
- send external communication
- browse the web
- execute arbitrary code
- own recurring schedule semantics
- replace cron
- replace adaptive memory retrieval
- write semantic, episodic, or procedural memory tables directly
- bypass semantic deduplication or procedural approval

## Memory Integration

Personal OS may read memory through approved repository or retrieval boundaries. If a completed local action creates memory-relevant information, background memory work should be represented through existing memory queues or memory stores, not direct table writes.

## Active Tool Shape

Every active Personal OS tool has metadata:

- stable `tool_id`
- `provider = personal_os`
- `implementation_type = local`
- risk class
- approval policy
- read/write capability
- external side effect flag set to false
- provider managed flag set to false
- observability metadata

## Deprecated Synthetic Tools

Synthetic context or lifecycle shims are removed from active binding or blocked:

- `sleep`
- `wake`
- `subscribe_event`
- `acquire_context`
- `release_context`

These tools should not reappear as normal active tools without a specific future design.

## Policy

Read-only Personal OS actions do not need approval. Bounded local writes are policy-known and audited. Sub-agent lifecycle writes require approval unless explicitly low-impact. Destructive local actions require approval or are blocked.

## Audit and Idempotency

Write-capable Personal OS actions record redacted audit entries when existing infrastructure supports it. Idempotency keys should be deterministic for retryable or approval-gated writes and should include tool ID, normalized payload hash, target resource, and session/operator context when available.

Audit must not store secrets, hidden reasoning, raw provider payloads, scratchpads, or chain-of-thought.
