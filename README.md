## Ivo

An autonomous, multi-provider AI Assistant and Agent Cockpit built with **LangGraph**, **LangChain**, **FastAPI**, **React**, **SQLite**, and a **cognee** knowledge graph for long-term memory.


---

## ðŸŒŸ Key Features

- **Multi-Provider LLM Integration**: Dynamically switch between **OpenAI** (`gpt-4o`, `gpt-4o-mini`), **Anthropic** (`claude-3-5-sonnet`, `claude-3-5-haiku`), **Google Gemini** (`gemini-3.8-flash`, `gemini-3.5-flash-lite`), and **xAI Grok** (`grok-2`).
- **Tiered LLM Architecture**: Primary LLM for planning & tool execution + Secondary cheaper LLM for background conversation summaries. One setting, `AI_PROVIDER=openai|gemini`, switches the default models (and cognee's) between OpenAI and Google Gemini.
- **Short-Term Memory Budgeting & Compaction**: Enforces strict 25% context budget reservations for System Prompt (`SOUL.md`), instructions, and retrieval context with automatic 75% budget compaction rules.
- **Long-Term Memory (cognee + Jev)**: One cognee knowledge graph holds everything the assistant knows long-term. Jev, a small routing model on any OpenAI-compatible endpoint, decides per message whether to store it and whether to recall memory. Worth-storing turns go to a per-conversation cognee session that merges into the main graph once the conversation is idle. Jev can also send unexpected medium-risk tool calls to human approval. Everything degrades safely: if Jev or cognee is unavailable, chat keeps working. The cockpit's **Memory Graph** tab shows the knowledge graph visually, and **Save to memory now** in Chat merges a conversation without waiting for it to go idle.
- **Human-In-The-Loop (HITL) Tool Safety**: Centralized policy and approval engine for high-risk real tool operations such as provider-managed sends, calendar writes, scheduler-triggered writes, and sensitive Personal OS actions.
- **Native Personal OS Tools & MCP Gateway**: 22 native Personal OS system tools + Live MCP Stdio/SSE protocol transport adapters.
- **Glassmorphism Web Cockpit**: Interactive React + Vite control panel with dark mode visuals and live telemetry tabs (Overview, Loop Timeline, Data Inspector, Memory, Tools, Scheduled Jobs, Tasks).

---

## ðŸš€ Quickstart Guide

### 1. Prerequisites
- Python **3.10+**
- Node.js **18+** & npm

### 2. Environment Setup
Copy `.env.example` to `.env` and supply your API keys:
```bash
cp .env.example .env
```

Ensure `.env` contains:
```ini
OPENAI_API_KEY=your_openai_api_key_here
ANTHROPIC_API_KEY=your_anthropic_api_key_here
GOOGLE_API_KEY=your_google_api_key_here
XAI_API_KEY=your_xai_api_key_here
```

### 3. Install Python Dependencies & Package
```bash
pip install -r requirements.txt
pip install -e .
```


### 4. Install Frontend Dependencies & Build Static Assets
```bash
cd frontend
npm install
npm run build
cd ..
```

---

## ðŸƒ Run Everything

Launch system components using the commands below:

| Component | Command | Details |
|---|---|---|
| **Backend REST API Server** | `python src/api/server.py` | Starts FastAPI backend & serves React web cockpit at `http://localhost:8000` |
| **Frontend Dev Server** | `cd frontend && npm run dev` | Runs Vite hot-reloading dev server at `http://localhost:5173` |
| **Frontend Production Build** | `cd frontend && npm run build` | Compiles production assets into `frontend/dist/` |
| **Background Scheduled Worker** | `python -m src.background_worker` | Runs recurring background polling loop with graceful SIGINT/SIGTERM shutdown |
| **Interactive CLI Agent** | `python src/main.py` | Launches interactive terminal CLI chat session |

---

## ðŸ“š Technical Documentation & Architecture

For complete system architecture diagrams, 21-table database schema specifications, Human-In-The-Loop (HITL) execution traces, backup/restore lifecycle details, background worker polling loop behavior, and provider setup guides, refer to:

ðŸ‘‰ **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**

---

## ðŸ§ª Running Automated Tests

Run the complete test suite (covering multi-provider models, REST API endpoints, short-term and cognee long-term memory, Personal OS tools, MCP gateway, HITL approvals, database migrations, background worker, system backup/restore, provider capability matrix, product polish, and documentation). Tests use an in-memory fake of cognee and never call the real service:


```bash
python -m pytest tests/
```


---

## Memory Architecture Runbooks

- **[Memory Architecture](docs/memory-architecture.md)**: LLM role split, durable memory jobs, short-term summaries, Jev routing, cognee session storage and idle merge, retrieval, tool review, configuration, observability, and legacy compatibility.
- **[Operator Runbook](docs/operator-runbook.md)**: install and configuration, backend/frontend startup, worker operation, health checks, memory search and retrieval trace, teaching facts and procedures, backup/restore, and incident recovery.
- **[Developer Testing Guide](docs/developer-testing.md)**: focused regression commands, fixture guidance, deterministic worker testing, fake LLM guidance, and static architecture scans.
- **[Memory Observability API](docs/api-memory-observability.md)**: read-only observability endpoints, request parameters, example responses, redaction rules, and privacy boundaries.
- **[Memory Failure Recovery](docs/memory-failure-recovery.md)**: queue, worker, cognee availability, provider outage, embedding mismatch, missing recall, secondary LLM, and DB recovery playbooks.
- **[Legacy Memory Backfill](docs/legacy-memory-backfill.md)**: one-time import of pre-cognee facts, episodes, and skills into cognee with `python -m src.memory.cognee_backfill`.

## Tools Architecture Runbooks

- **[Tools Architecture](docs/tools-architecture.md)**: final local/MCP/removed tool taxonomy, registry, routing, policy, invocation, audit, observability, sandbox removal proof, and memory boundaries.
- **[Tools Operator Runbook](docs/tools-operator-runbook.md)**: backend/frontend startup, provider status checks, cron operations, approval review, Personal OS inspection, and troubleshooting.
- **[MCP Wiring Guide](docs/tools-mcp-wiring.md)**: provider-managed MCP rule, config shape, discovery, invocation, and safe manual validation.
- **[Tools Security Policy](docs/tools-security-policy.md)**: HITL policy classes, approval previews, approval resume safety, secondary LLM boundaries, and redaction rules.
- **[Cron Jobs](docs/tools-cron-jobs.md)**: durable local scheduler model, one-time and recurring schedules, timezone handling, missed-run policy, and run attempts.
- **[Personal OS](docs/tools-personal-os.md)**: bounded local responsibilities, non-responsibilities, memory boundaries, audit, idempotency, and deprecated synthetic tools.
- **[MCP Provider Validation](docs/tools-mcp-provider-validation.md)**: manual checklist for Tavily/DuckDuckGo, Google Calendar, Gmail, WhatsApp, and Telegram MCP providers. Mocked tests do not prove real provider availability.

