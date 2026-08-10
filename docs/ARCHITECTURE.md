# ASTRA (Autonomous System for Tasks, Reasoning & Assistance) - Architecture & System Technical Specification

This document provides the authoritative technical architecture, schema specifications, Human-In-The-Loop (HITL) workflows, backup lifecycle, background worker specification, provider setup instructions, and known limitations for **ASTRA**.

---

## 1. High-Level System Architecture

ASTRA is built as an autonomous, multi-provider personal assistant operating on a hybrid local-first architecture.

```text
                               +----------------------------------+
                               |     React + Vite Cockpit UI      |
                               |  (Overview, Loop, Tasks, Data)   |
                               +----------------------------------+
                                                |
                                          HTTP REST API
                                                v
                               +----------------------------------+
                               |        FastAPI Web Server        |
                               |          (src/api/server.py)     |
                               +----------------------------------+
                                                |
                                                v
                               +----------------------------------+
                               |     LangGraph Harness Loop       |
                               |        (src/harness/graph.py)    |
                               +----------------------------------+
                                 /              |               \
                                /               |                \
                               v                v                 v
            +--------------------+   +-------------------+   +--------------------+
            | Primary LLM Tier   |   | Memory Subsystems |   | Tool Infrastructure|
            | (OpenAI/Anthropic/ |   | (Episodic,        |   | (22 OS Tools +     |
            | Gemini/Grok)       |   |  Semantic FTS5,   |   |  MCP Gateway)      |
            +--------------------+   |  Procedural)      |   +--------------------+
                                     +-------------------+
                                                |
                                                v
                                     +-------------------+
                                     | SQLite state.db   |
                                     |  (FTS5 Tables)    |
                                     +-------------------+
```

---

## 2. Feature Status & Capability Matrix

ASTRA categorizes tool features into three distinct operational modes:

| Feature / Tool Component | Execution Status | Provider Adapter / Engine | Required Environment Variables |
| :--- | :--- | :--- | :--- |
| **Email Reading** | MCP / UNAVAILABLE | Provider-managed Gmail MCP | `.agent/mcp_config.json` or app connector |
| **Email Transmit** | MCP / UNAVAILABLE | Provider-managed Gmail MCP (Gated HITL) | `.agent/mcp_config.json` or app connector |
| **Web Search** | MCP / UNAVAILABLE | Provider-managed Tavily or DuckDuckGo MCP | `.agent/mcp_config.json` or app connector |
| **Telegram Messaging**| MCP / UNAVAILABLE | Provider-managed Telegram MCP | `.agent/mcp_config.json` or app connector |
| **WhatsApp Messaging**| MCP / UNAVAILABLE | Provider-managed WhatsApp MCP | `.agent/mcp_config.json` or app connector |
| **Google Calendar** | MCP / UNAVAILABLE | Provider-managed Google Calendar MCP | `.agent/mcp_config.json` or app connector |
| **Task Management** | LOCAL-ONLY | SQLite `tasks` table | None |
| **Sub-Agent Spawn** | REAL / LOCAL | LangChain Async Sub-Agent | None |
| **System Backup** | REAL | Zip compressed archive | None |

---

## 3. SQLite Database Schema Specification (`.agent/state.db`)

ASTRA uses an integrated SQLite database (`.agent/state.db`) managed via versioned schema migrations (`src/db_migrations.py`, current version: **v7**).

### Core Tables

1. **`episodes`** (FTS5 Virtual Table):
   - Stores historical conversation turns and outcomes for semantic retrieval.
   - Fields: `session_id`, `timestamp`, `content`, `tool_calls`, `outcome`.

2. **`facts`** (FTS5 Virtual Table):
   - Stores extracted long-term memory facts auto-synced with `.agent/MEMORY.md`.
   - Fields: `category`, `fact_text`, `source`, `confidence`, `created_at`.

3. **`skills`** (FTS5 Virtual Table):
   - Stores procedural memory skills auto-synced with `.agent/SKILL.md`.
   - Fields: `name`, `description`, `trigger`, `instructions`, `created_at`.

4. **`checkpoints`**:
   - Stores LangGraph state checkpoints for session pause, HITL resumption, and context recovery.
   - Fields: `id`, `session_id`, `checkpoint_data`, `created_at`.

5. **`approval_requests`**:
   - Stores pending and processed Human-In-The-Loop approval requests.
   - Fields: `id`, `session_id`, `tool_name`, `tool_args_json`, `risk_level`, `status`, `idempotency_key`, `execution_status`, `created_at`.

6. **`audit_logs`**:
   - Security audit trail for medium/high risk operation tracking.
   - Fields: `id`, `session_id`, `event_type`, `tool_name`, `user_decision`, `payload_json`, `created_at`.

7. **`tool_calls`**:
   - Structured registry of emitted LLM tool call requests.
   - Fields: `id`, `session_id`, `tool_name`, `tool_args`, `status`, `created_at`.

8. **`tool_results`**:
   - Execution outputs linked to `tool_calls.id`.
   - Fields: `id`, `tool_call_id`, `session_id`, `tool_name`, `result_content`, `status`, `created_at`.

9. **`tasks`**:
   - Task Board items managed by Personal OS tools (`create_task`, `update_task`).
   - Fields: `id`, `title`, `description`, `status`, `assigned_to`, `created_at`.

10. **`sub_agents`**:
    - Active and completed sub-agent execution tracking.
    - Fields: `id`, `parent_session_id`, `role`, `status`, `created_at`.

11. **`scheduled_jobs`**:
    - Recurring cron or timestamp scheduled background tasks.
    - Fields: `id`, `cron_or_timestamp`, `task_payload`, `status`, `next_run_at`, `created_at`.

12. **`loop_events`**:
    - Step-by-step trace of agent reasoning and tool execution cycles.
    - Fields: `id`, `session_id`, `step_index`, `step_type`, `reasoning`, `tool_name`, `tool_args_json`, `tool_result`, `created_at`.

13. **`calendar_events`**:
    - Local SQLite calendar storage with start/end time conflict checking.
    - Fields: `id`, `title`, `start_time`, `end_time`, `attendees`, `location`, `status`, `created_at`.

14. **`emails`**:
    - Local email store for drafts, sent items, and inbox indexing.
    - Fields: `id`, `sender`, `recipient`, `subject`, `body`, `folder`, `status`, `created_at`.

15. **`whatsapp_messages`**:
    - Logged WhatsApp messages.
    - Fields: `id`, `sender`, `recipient`, `message`, `status`, `created_at`.

16. **`telegram_messages`**:
    - Logged Telegram chat messages.
    - Fields: `id`, `chat_id`, `message`, `status`, `created_at`.

17. **`schema_migrations`**:
    - Applied schema versions tracking (`version`, `description`, `applied_at`).

---

## 4. Human-In-The-Loop (HITL) Exact Sequence

```text
[User Chat Request]
       |
       v
[Agent Loop Node (node_agent)] ---> Emits high-risk ToolCall (e.g. email_send, calendar_create_event)
       |
       v
[Risk Classifier (classify_tool_risk)] ---> Detects HIGH risk
       |
       v
[HITL Gate]
  1. Generate Idempotency Key (SHA-256 hash of session + tool + args)
  2. Insert approval request into SQLite `approval_requests` (status='PENDING')
  3. Create LangGraph Checkpoint in `checkpoints`
  4. Interrupt Graph & Return {"status": "APPROVAL_REQUIRED", "approval_request": ...}
       |
       +<------------------- [User Review in Cockpit Approval Inbox] -------------------+
       |                                                                                |
       v                                                                                v
[User Clicks "Approve"]                                                    [User Clicks "Reject"]
       |                                                                                |
[POST /api/approval/decision (decision='APPROVED')]                        [POST /api/approval/decision (decision='REJECTED')]
       |                                                                                |
  1. Verify idempotency key (Block duplicate execution)                      1. Update status='REJECTED'
  2. Update status='APPROVED', execution_status='APPROVED_EXECUTED'           2. Append Rejection Observation ToolMessage
  3. Restore Checkpoint State                                                 3. Resume Graph Loop for alternative plan
  4. Execute Tool Function
  5. Log ToolMessage output to Graph State
  6. Resume Agent Loop to produce final response
```

---

## 5. System Backup & Restore Lifecycle

### Export Backup (`export_agent_backup()`)
- Packages `state.db`, `SOUL.md`, `MEMORY.md`, and `SKILL.md` into a compressed zip archive (`agent_backup_YYYYMMDD_HHMMSS.zip`).
- Automatically triggers `rotate_backups(max_backups=5)` to prune oldest archives exceeding 5 files.

### Restore Safety Protocol (`restore_agent_backup()`)
1. Validates that the file is a valid zip archive.
2. Inspects `state.db` bytes inside the zip to verify the SQLite 16-byte magic header (`b"SQLite format 3\x00"`). Raises `ValueError` if missing or corrupt.
3. Creates a pre-restore rollback copy `.agent/state.db.bak` of the active database prior to overwriting.
4. Overwrites workspace files and reports restored file list.

---

## 6. Background Scheduled Worker Behavior

- Entrypoint: `python -m src.background_worker` in `src/background_worker.py`.
- Polling Loop: Runs every 5 seconds, querying `scheduled_jobs` table `WHERE status IN ('PENDING', 'ACTIVE') AND next_run_at <= CURRENT_TIMESTAMP`.
- Execution: Dispatches scheduled tasks via LangGraph agent runner. Updates job status to `COMPLETED` (or calculates next run time for recurring cron expressions).
- Signal Safety: Registers `SIGINT` and `SIGTERM` handlers for clean worker termination without corrupting active SQLite transactions.

---

## 7. Provider Setup & Configuration Guide

### 1. Primary & Secondary LLM Setup
Configure API keys in `.env`:
```ini
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_API_KEY=AIza...
XAI_API_KEY=xai-...
```

### 2. Provider-managed MCP tools
Configure search, Google Calendar, Gmail, WhatsApp, and Telegram through `.agent/mcp_config.json` or provider-managed app connectors. The local assistant discovers tools through MCP `tools/list` and invokes provider actions only through MCP `tools/call`.

Direct local provider credentials for Tavily REST, DuckDuckGo libraries, Google Calendar REST, SMTP/IMAP, WhatsApp Graph, and Telegram Bot API are not consumed by the local assistant runtime.

---

## 8. Known Limitations & Development Scope

1. **Single-User Local Desktop Boundaries**:
   - ASTRA is designed for single-user desktop or personal server deployment. Multi-tenant auth/isolation is not enabled.
2. **SQLite Write Lock Boundaries**:
   - SQLite uses file-level locking during write transactions. High-concurrency simultaneous API calls may encounter brief database busy locks.
