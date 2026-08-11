## 🚀 ASTRA (Autonomous System for Tasks, Reasoning & Assistance)

An autonomous, multi-provider AI Assistant and Agent Cockpit built with **LangGraph**, **LangChain**, **FastAPI**, **React**, and **SQLite FTS5**.


---

## 🌟 Key Features

- **Multi-Provider LLM Integration**: Dynamically switch between **OpenAI** (`gpt-4o`, `gpt-4o-mini`), **Anthropic** (`claude-3-5-sonnet`, `claude-3-5-haiku`), **Google Gemini** (`gemini-1.5-pro`, `gemini-1.5-flash`), and **xAI Grok** (`grok-2`).
- **Tiered LLM Architecture**: Primary LLM for planning & tool execution + Secondary cheaper LLM for background summaries, fact extraction, and memory consolidation.
- **Short-Term Memory Budgeting & Compaction**: Enforces strict 25% context budget reservations for System Prompt (`SOUL.md`), instructions, and retrieval context with automatic 75% budget compaction rules.
- **Long-Term Memory Systems**:
  - **Semantic Memory**: FTS5 Top-K keyword search & auto-synced `.agent/MEMORY.md`.
  - **Episodic Memory**: FTS5 session history & Secondary LLM structured JSON summaries.
  - **Procedural Memory**: Interactive skills manager & auto-synced `.agent/SKILL.md`.
- **Human-In-The-Loop (HITL) Tool Safety**: Deterministic risk classifier & approval engine for high-risk tool operations (`bank_transfer`, `delete_database`, `production_deploy`, `calendar_create_event`).
- **Native Personal OS Tools & MCP Gateway**: 22 native Personal OS system tools + Live MCP Stdio/SSE protocol transport adapters.
- **Glassmorphism Web Cockpit**: Interactive React + Vite control panel with dark mode visuals and live telemetry tabs (Overview, Loop Timeline, Data Inspector, Memory, Tools, Scheduled Jobs, Tasks).

---

## 🚀 Quickstart Guide

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

## 🏃 Run Everything

Launch system components using the commands below:

| Component | Command | Details |
|---|---|---|
| **Backend REST API Server** | `python src/api/server.py` | Starts FastAPI backend & serves React web cockpit at `http://localhost:8000` |
| **Frontend Dev Server** | `cd frontend && npm run dev` | Runs Vite hot-reloading dev server at `http://localhost:5173` |
| **Frontend Production Build** | `cd frontend && npm run build` | Compiles production assets into `frontend/dist/` |
| **Background Scheduled Worker** | `python -m src.background_worker` | Runs recurring background polling loop with graceful SIGINT/SIGTERM shutdown |
| **Interactive CLI Agent** | `python src/main.py` | Launches interactive terminal CLI chat session |

---

## 📚 Technical Documentation & Architecture

For complete system architecture diagrams, 21-table database schema specifications, Human-In-The-Loop (HITL) execution traces, backup/restore lifecycle details, background worker polling loop behavior, and provider setup guides, refer to:

👉 **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**

---

## 🧪 Running Automated Tests

Run the complete verified test suite (**181 tests passed/skipped, 100% success rate** covering multi-provider models, REST API endpoints, memory systems, Personal OS tools, MCP gateway, HITL approvals, database migrations, background worker, system backup/restore, provider capability matrix, product polish, and documentation):


```bash
python -m pytest tests/
```


---

## Memory Architecture Runbooks

- **[Memory Architecture](docs/memory-architecture.md)**: final primary/secondary LLM split, durable memory jobs, summaries, structured episodes, semantic consolidation, procedural skills, retrieval, observability, table ownership, and legacy compatibility.
- **[Operator Runbook](docs/operator-runbook.md)**: backend/frontend startup, explicit worker operation, health checks, retrieval trace, semantic/procedural review, approval workflows, backup/restore, and incident recovery.
- **[Developer Testing Guide](docs/developer-testing.md)**: focused regression commands, fixture guidance, deterministic worker testing, fake LLM guidance, and static architecture scans.
- **[Memory Observability API](docs/api-memory-observability.md)**: read-only observability endpoints, request parameters, example responses, redaction rules, and privacy boundaries.
- **[Memory Failure Recovery](docs/memory-failure-recovery.md)**: queue, worker, secondary LLM, consolidation, approval, skill reload, retrieval, and DB recovery playbooks.
- **[Legacy Memory Backfill](docs/legacy-memory-backfill.md)**: documentation-only dry-run strategy for future optional legacy data backfill.

## Tools Architecture Runbooks

- **[Tools Architecture](docs/tools-architecture.md)**: final local/MCP/removed tool taxonomy, registry, routing, policy, invocation, audit, observability, sandbox removal proof, and memory boundaries.
- **[Tools Operator Runbook](docs/tools-operator-runbook.md)**: backend/frontend startup, provider status checks, cron operations, approval review, Personal OS inspection, and troubleshooting.
- **[MCP Wiring Guide](docs/tools-mcp-wiring.md)**: provider-managed MCP rule, config shape, discovery, invocation, and safe manual validation.
- **[Tools Security Policy](docs/tools-security-policy.md)**: HITL policy classes, approval previews, approval resume safety, secondary LLM boundaries, and redaction rules.
- **[Cron Jobs](docs/tools-cron-jobs.md)**: durable local scheduler model, one-time and recurring schedules, timezone handling, missed-run policy, and run attempts.
- **[Personal OS](docs/tools-personal-os.md)**: bounded local responsibilities, non-responsibilities, memory boundaries, audit, idempotency, and deprecated synthetic tools.
- **[MCP Provider Validation](docs/tools-mcp-provider-validation.md)**: manual checklist for Tavily/DuckDuckGo, Google Calendar, Gmail, WhatsApp, and Telegram MCP providers. Mocked tests do not prove real provider availability.
