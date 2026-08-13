import os
import json
import uuid
import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from src.db import get_connection
from src.personal_os.scheduling import heartbeat, schedule_job, cancel_job
from src.personal_os.registry import get_os_tool_catalog
from src.mcp_gateway.registry import get_external_api_tool_catalog, get_mcp_tool_catalog
from src.memory.semantic import get_all_semantic_facts, add_semantic_fact, search_facts_top_k, sync_memory_md
from src.memory.episodic import search_episodes_fts
from src.memory.procedural import (
    add_procedural_skill,
    get_all_procedural_skills,
    delete_procedural_skill,
    sync_skill_md
)
from src.memory.short_term import get_raw_turns
from src.hitl.approval_engine import create_approval_request, get_all_approval_requests, process_approval_decision

from src.harness.graph import agent_app, resume_graph_after_approval
from src.harness.models import get_model_catalog
from src.harness.llm_router import normalize_provider
from src.mcp_gateway.search import perform_web_search

from src.mcp_gateway.communication import (
    email_read, email_search, email_draft, email_send
)

from src.mcp_gateway.calendar import (
    calendar_inspect_availability, calendar_create_event, calendar_update_event, calendar_delete_event
)

from src.config import SOUL_PATH, SKILL_PATH, MEMORY_PATH
from src.memory.config import load_memory_config
from src.memory.skill_promotion import ProceduralSkillApprovalRepository, process_procedural_skill_approval_decision
from src.memory.observability import (
    get_dead_letter_observability,
    get_jobs_observability,
    get_memory_health_summary,
    get_observability_overview,
    get_procedural_observability,
    get_retrieval_trace,
    get_semantic_observability,
    get_skill_observability,
    get_worker_observability,
)
from src.startup import ensure_system_initialized
from src.personal_os.backup import export_agent_backup, restore_agent_backup

# Guarantee system directory and database schema initialization on server boot
ensure_system_initialized()


app = FastAPI(
    title="24x7 Personal Assistant API",
    description="REST API Gateway for LangGraph Agent Harness, Memory, Tools, HITL, and Multi-Provider LLMs",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Pydantic Data Models ---
class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = "default_session"
    provider: Optional[str] = "openai"
    model_name: Optional[str] = "gpt-4o-mini"
    secondary_provider: Optional[str] = "openai"
    secondary_model_name: Optional[str] = "gpt-4o-mini"


class FactRequest(BaseModel):
    category: str
    fact_text: str

class SkillRequest(BaseModel):
    name: str
    description: str
    trigger_keywords: str
    execution_steps: str

class DecisionRequest(BaseModel):
    decision: str  # "APPROVED" or "REJECTED"

class ProviderConfigUpdateRequest(BaseModel):
    values: Dict[str, Any] = {}


class ScheduledJobRequest(BaseModel):
    cron_or_timestamp: str
    task_payload: str


class CronScheduleRequest(BaseModel):
    schedule_type: str
    target_tool_id: str = "heartbeat"
    target_payload: Dict[str, Any] = {}
    cron_expression: Optional[str] = None
    run_at: Optional[str] = None
    timezone: Optional[str] = "UTC"
    missed_run_policy: Optional[str] = None
    max_catchup_runs: int = 1
    created_by: Optional[str] = "api"


class CronSchedulePatchRequest(BaseModel):
    schedule_type: Optional[str] = None
    target_tool_id: Optional[str] = None
    target_payload: Optional[Dict[str, Any]] = None
    cron_expression: Optional[str] = None
    run_at: Optional[str] = None
    timezone: Optional[str] = None
    missed_run_policy: Optional[str] = None
    max_catchup_runs: Optional[int] = None
    status: Optional[str] = None

class RetrievalTraceRequest(BaseModel):
    query: str
    session_id: Optional[str] = None
    provider: Optional[str] = "openai"
    model_name: Optional[str] = "gpt-4o-mini"
    include_candidates: bool = True
    include_prompt_block: bool = False
    max_candidates: int = 20
ALLOWED_DATA_TABLES = [
    "episodes", "facts", "skills", "checkpoints", "approval_requests",
    "sub_agents", "tasks", "scheduled_jobs", "resource_locks", "events_log",
    "context_blocks", "raw_turns", "pending_facts", "loop_events",
    "calendar_events", "emails", "whatsapp_messages", "telegram_messages",
    "audit_logs", "tool_calls", "tool_results",
    "memory_jobs", "dead_letter_jobs", "worker_heartbeats", "summary_blocks",
    "structured_episodes", "pending_fact_candidates", "semantic_embeddings",
    "semantic_dedup_events", "consolidation_runs", "skill_candidates",
    "skill_versions", "skill_usage_stats", "procedural_skill_approvals",
    "tool_schedules", "tool_schedule_runs"
]


def _generate_deterministic_thread_title(message: str) -> str:
    words = []
    stop_words = {"a", "an", "and", "are", "for", "how", "the", "to", "do", "i", "me", "my"}
    for raw in message.replace("_", " ").split():
        cleaned = "".join(ch for ch in raw if ch.isalnum())
        if not cleaned or cleaned.lower() in stop_words:
            continue
        words.append(cleaned[:1].upper() + cleaned[1:])
        if len(words) >= 5:
            break
    return " ".join(words) if words else "New Chat"
# --- API Endpoints ---

@app.get("/api/health")
def api_health():
    from src.harness.models import is_valid_key

    hb = heartbeat.invoke({})
    return {
        "status": "online",
        "heartbeat": hb,
        "backend": "LangGraph + SQLite FTS5",
        "llm_available": is_valid_key(os.getenv("OPENAI_API_KEY"))
            or is_valid_key(os.getenv("ANTHROPIC_API_KEY"))
            or is_valid_key(os.getenv("GOOGLE_API_KEY"))
            or is_valid_key(os.getenv("XAI_API_KEY")),
    }

class RenameSessionRequest(BaseModel):
    new_session_id: str

@app.get("/api/sessions")
def api_get_sessions():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT session_id FROM raw_turns ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()
    return {"sessions": [r["session_id"] for r in rows]}

@app.get("/api/history/{session_id}")
@app.get("/api/loop/events/{session_id}")
@app.get("/api/loop/events")
def api_get_history(session_id: Optional[str] = "default_session"):
    sid = session_id or "default_session"
    try:
        turns = get_raw_turns(session_id=sid)
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, step_index, step_type, reasoning, tool_name, tool_args_json, tool_result, created_at
            FROM loop_events
            WHERE session_id = ?
            ORDER BY rowid ASC
            """,
            (sid,)
        )
        db_events = cursor.fetchall()
        conn.close()
        loop_trace = [dict(r) for r in db_events]
        return {
            "session_id": sid,
            "turns": turns,
            "total_turns": len(turns),
            "loop_events": loop_trace,
            "loop_trace": loop_trace
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve history for session '{sid}': {str(e)}")


@app.put("/api/history/{session_id}")
def api_rename_session(session_id: str, req: RenameSessionRequest):
    new_id = req.new_session_id.strip()
    if not new_id:
        raise HTTPException(status_code=400, detail="New session_id cannot be empty.")
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE raw_turns SET session_id = ? WHERE session_id = ?", (new_id, session_id))
    cursor.execute("UPDATE loop_events SET session_id = ? WHERE session_id = ?", (new_id, session_id))
    cursor.execute("UPDATE approval_requests SET session_id = ? WHERE session_id = ?", (new_id, session_id))
    conn.commit()
    conn.close()
    return {"status": "success", "old_session_id": session_id, "new_session_id": new_id}

@app.delete("/api/history/{session_id}")
def api_delete_session(session_id: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM raw_turns WHERE session_id = ?", (session_id,))
    cursor.execute("DELETE FROM loop_events WHERE session_id = ?", (session_id,))
    cursor.execute("DELETE FROM approval_requests WHERE session_id = ?", (session_id,))
    conn.commit()
    conn.close()
    return {"status": "success", "message": f"Session '{session_id}' deleted."}

@app.get("/api/models")
def api_get_models():
    return {
        "catalog": get_model_catalog(),
        "memory_defaults": load_memory_config().to_dict()
    }


@app.post("/api/chat")
def api_chat(req: ChatRequest):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    target_session_id = req.session_id
    session_title = req.session_id

    # Check turn count for session to identify first message in a thread
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM raw_turns WHERE session_id = ?", (req.session_id,))
    turn_count = cursor.fetchone()[0]
    conn.close()

    norm_provider = normalize_provider(req.provider)
    norm_sec_provider = normalize_provider(req.secondary_provider)

    # On first turn of a temporary thread (default_session, new_chat, etc.), generate short concise topic title (ChatGPT style)
    is_temp_session = req.session_id in ("default_session", "new_session", "new_chat") or req.session_id.startswith(("new_", "temp_", "sess_new_"))
    if turn_count == 0 and is_temp_session:
        topic_title = _generate_deterministic_thread_title(req.message)
        if topic_title and topic_title != "New Chat":
            target_session_id = topic_title
            session_title = topic_title
            # If session ID changed from initial temp ID, update any existing records
            if req.session_id != target_session_id:
                conn_u = get_connection()
                cursor_u = conn_u.cursor()
                cursor_u.execute("UPDATE raw_turns SET session_id = ? WHERE session_id = ?", (target_session_id, req.session_id))
                cursor_u.execute("UPDATE loop_events SET session_id = ? WHERE session_id = ?", (target_session_id, req.session_id))
                cursor_u.execute("UPDATE approval_requests SET session_id = ? WHERE session_id = ?", (target_session_id, req.session_id))
                conn_u.commit()
                conn_u.close()

    input_state = {
        "messages": [HumanMessage(content=req.message)],
        "session_id": target_session_id,
        "summary": "",
        "token_count": 0,
        "retrieval_triggered": False,
        "retrieved_memories": [],
        "pending_approval_id": None,
        "approval_status": None,
        "provider": norm_provider,
        "model_name": req.model_name or "gpt-4o-mini",
        "secondary_provider": norm_sec_provider,
        "secondary_model_name": req.secondary_model_name or "gpt-4o-mini"
    }


    try:
        result = agent_app.invoke(input_state)
        messages = result.get("messages", [])

        # Find latest AI or System message
        last_ai_content = ""
        for m in reversed(messages):
            if isinstance(m, (AIMessage, SystemMessage)) and m.content:
                last_ai_content = str(m.content)
                break

        # Fetch all ordered loop step events for target_session_id
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, step_index, step_type, reasoning, tool_name, tool_args_json, tool_result, created_at
            FROM loop_events
            WHERE session_id = ?
            ORDER BY rowid ASC
            """,
            (target_session_id,)
        )
        db_events = cursor.fetchall()
        conn.close()

        loop_trace = [dict(r) for r in db_events] if db_events else result.get("loop_events", [])

        return {
            "session_id": target_session_id,
            "session_title": session_title,
            "response": last_ai_content or "[No response generated]",
            "retrieval_triggered": result.get("retrieval_triggered", False),
            "retrieved_memories": result.get("retrieved_memories", []),
            "pending_approval_id": result.get("pending_approval_id"),
            "approval_status": result.get("approval_status"),
            "iterations": result.get("loop_count", 1),
            "tools_used": result.get("tools_used", []),
            "loop_events": loop_trace,
            "loop_trace": loop_trace
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent harness error: {str(e)}")



# --- Memory Endpoints ---

@app.get("/api/memory")
def api_get_memory():
    facts = get_all_semantic_facts()
    return {"facts": facts, "total_facts": len(facts)}

@app.post("/api/memory/fact")
def api_add_fact(req: FactRequest):
    if not req.fact_text.strip():
        raise HTTPException(status_code=400, detail="Fact text cannot be empty.")
    add_semantic_fact(category=req.category, fact_text=req.fact_text, source="user_api")
    return {"status": "success", "message": "Fact saved and MEMORY.md synced."}

@app.get("/api/memory/full")
def api_get_full_memory(query: Optional[str] = None):
    q = query or ""
    facts = search_facts_top_k(query=q, k=10) if q else get_all_semantic_facts()
    episodes = search_episodes_fts(query=q, limit=10) if q else []

    soul_content = SOUL_PATH.read_text(encoding="utf-8") if SOUL_PATH.exists() else ""
    skill_content = SKILL_PATH.read_text(encoding="utf-8") if SKILL_PATH.exists() else ""
    memory_content = MEMORY_PATH.read_text(encoding="utf-8") if MEMORY_PATH.exists() else ""

    return {
        "facts": facts,
        "episodes": episodes,
        "soul_md": soul_content,
        "skill_md": skill_content,
        "memory_md": memory_content
    }

# --- Memory Observability Endpoints ---

@app.get("/api/memory/observability/health")
def api_memory_observability_health(stale_after_seconds: int = 120):
    return get_memory_health_summary(stale_after_seconds=stale_after_seconds)

@app.get("/api/memory/observability/jobs")
def api_memory_observability_jobs(
    session_id: Optional[str] = None,
    status: Optional[str] = None,
    job_type: Optional[str] = None,
    limit: int = 50,
    include_payload: bool = False,
):
    return get_jobs_observability(
        session_id=session_id,
        status=status,
        job_type=job_type,
        limit=limit,
        include_payload=include_payload,
    )

@app.get("/api/memory/observability/workers")
def api_memory_observability_workers(
    stale_after_seconds: int = 120,
    include_host_metadata: bool = False,
):
    return get_worker_observability(
        stale_after_seconds=stale_after_seconds,
        include_host_metadata=include_host_metadata,
    )

@app.get("/api/memory/observability/dead-letter")
def api_memory_observability_dead_letter(limit: int = 50, include_details: bool = False):
    return get_dead_letter_observability(limit=limit, include_details=include_details)

@app.post("/api/memory/observability/retrieval/trace")
def api_memory_observability_retrieval_trace(req: RetrievalTraceRequest):
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="query must be non-empty")
    try:
        return get_retrieval_trace(
            query=req.query,
            session_id=req.session_id,
            provider=req.provider,
            model_name=req.model_name,
            include_candidates=req.include_candidates,
            include_prompt_block=req.include_prompt_block,
            max_candidates=req.max_candidates,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

@app.get("/api/memory/observability/semantic")
def api_memory_observability_semantic(
    session_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
):
    return get_semantic_observability(session_id=session_id, status=status, limit=limit)

@app.get("/api/memory/observability/procedural")
def api_memory_observability_procedural(status: Optional[str] = None, limit: int = 100):
    return get_procedural_observability(status=status, limit=limit)

@app.get("/api/memory/observability/skills")
def api_memory_observability_skills(include_archived: bool = False):
    return get_skill_observability(include_archived=include_archived)

@app.get("/api/memory/observability/overview")
def api_memory_observability_overview():
    return get_observability_overview()

# --- Procedural Skills Endpoints ---

@app.get("/api/skills")
def api_get_skills():
    skills = get_all_procedural_skills()
    return {"skills": skills, "total_skills": len(skills)}

@app.post("/api/skills")
def api_add_skill(req: SkillRequest):
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="Skill name cannot be empty.")
    add_procedural_skill(
        name=req.name,
        description=req.description,
        trigger_keywords=req.trigger_keywords,
        execution_steps=req.execution_steps
    )
    return {"status": "success", "message": f"Skill '{req.name}' saved as a versioned SKILL.md file"}

@app.delete("/api/skills/{skill_name}")
def api_delete_skill(skill_name: str):
    delete_procedural_skill(name=skill_name)
    return {"status": "success", "message": f"Skill '{skill_name}' disabled and archived"}

# --- Calendar Endpoints ---

class CalendarEventRequest(BaseModel):
    title: str
    start_time: str
    end_time: str
    attendees: Optional[str] = ""
    location: Optional[str] = ""
    status: Optional[str] = "CONFIRMED"

@app.get("/api/calendar/events")
def api_get_calendar_events(start_date: Optional[str] = None, end_date: Optional[str] = None):
    result = calendar_inspect_availability.invoke({
        "start_date": start_date or "",
        "end_date": end_date or "",
    })
    return {"events": [], "total_events": 0, "result": result}

@app.post("/api/calendar/events")
def api_create_calendar_event(req: CalendarEventRequest):
    args = {
        "title": req.title,
        "start_time": req.start_time,
        "end_time": req.end_time,
        "attendees": req.attendees or "",
        "location": req.location or ""
    }
    app_req = create_approval_request(
        session_id="rest_api_calendar",
        tool_name="calendar_create_event",
        tool_args=args,
        reason=f"Direct REST API call to create calendar event '{req.title}'"
    )
    return {
        "status": "APPROVAL_REQUIRED",
        "approval_request": app_req,
        "message": f"Calendar event creation for '{req.title}' is classified as High Risk and requires human authorization."
    }

@app.put("/api/calendar/events/{event_id}")
def api_update_calendar_event(event_id: str, req: CalendarEventRequest):
    res = calendar_update_event.invoke({
        "event_id": event_id,
        "title": req.title,
        "start_time": req.start_time,
        "end_time": req.end_time,
        "attendees": req.attendees or "",
        "location": req.location or "",
        "status": req.status or "CONFIRMED"
    })
    return {"status": "success", "result": res}

@app.delete("/api/calendar/events/{event_id}")
def api_delete_calendar_event(event_id: str):
    app_req = create_approval_request(
        session_id="rest_api_calendar",
        tool_name="calendar_delete_event",
        tool_args={"event_id": event_id},
        reason=f"Direct REST API call to delete calendar event '{event_id}'"
    )
    return {
        "status": "APPROVAL_REQUIRED",
        "approval_request": app_req,
        "message": f"Calendar event deletion for '{event_id}' is classified as High Risk and requires human authorization."
    }

# --- Email Endpoints ---

class EmailMessageRequest(BaseModel):
    to: str
    subject: str
    body: str

@app.get("/api/email/messages")
def api_get_email_messages(limit: int = 10, query: Optional[str] = None):
    if query:
        result = email_read.invoke({"limit": limit}) if not query.strip() else email_search.invoke({"query": query})
    else:
        result = email_read.invoke({"limit": limit})
    return {"messages": [], "total_messages": 0, "result": result}

@app.post("/api/email/draft")
def api_create_email_draft(req: EmailMessageRequest):
    res = email_draft.invoke({"to": req.to, "subject": req.subject, "body": req.body})
    return {"status": "success", "result": res}

@app.post("/api/email/send")
def api_send_email(req: EmailMessageRequest):
    args = {"to": req.to, "subject": req.subject, "body": req.body}
    app_req = create_approval_request(
        session_id="rest_api_email",
        tool_name="email_send",
        tool_args=args,
        reason=f"Direct REST API call to send email to '{req.to}'"
    )
    return {
        "status": "APPROVAL_REQUIRED",
        "approval_request": app_req,
        "message": f"Outbound email transmission to '{req.to}' is classified as High Risk and requires human authorization."
    }

# --- Search Endpoint ---

@app.get("/api/search")
def api_search_web(q: str, max_results: int = 5):
    if not q.strip():
        raise HTTPException(status_code=400, detail="Search query 'q' cannot be empty.")
    results = perform_web_search(query=q.strip(), max_results=max_results)
    return {"query": q, "results": results, "total_results": len(results)}

# --- Provider Configuration Endpoints ---

@app.get("/api/config/providers")
def api_get_provider_configs():
    from src.tools.provider_config import list_provider_config_statuses

    return list_provider_config_statuses()


@app.post("/api/config/providers/{provider_id}")
def api_save_provider_config(provider_id: str, req: ProviderConfigUpdateRequest):
    from src.tools.provider_config import save_provider_config

    result = save_provider_config(provider_id, req.values or {})
    if result is None:
        raise HTTPException(status_code=404, detail="Unknown provider.")
    return result


@app.delete("/api/config/providers/{provider_id}/secret")
def api_clear_provider_secret(provider_id: str, field_name: Optional[str] = None):
    from src.tools.provider_config import clear_provider_secret

    result = clear_provider_secret(provider_id, field_name=field_name)
    if result is None:
        raise HTTPException(status_code=404, detail="Unknown provider.")
    return result


@app.post("/api/config/providers/{provider_id}/validate")
def api_validate_provider_config(provider_id: str):
    from src.tools.provider_config import validate_provider_config

    result = validate_provider_config(provider_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Unknown provider.")
    return result

# --- Tools Endpoints ---







@app.get("/api/tools")
def api_get_tools():
    os_tools = get_os_tool_catalog()
    mcp_tools = get_mcp_tool_catalog()
    external_api_tools = get_external_api_tool_catalog()
    return {
        "total_tools": len(os_tools) + len(mcp_tools) + len(external_api_tools),
        "personal_os_tools": os_tools,
        "mcp_tools": mcp_tools,
        "external_api_tools": external_api_tools,
    }


@app.get("/api/tools/status")
def api_tools_status():
    from src.tools.observability import get_tools_status_observability

    return get_tools_status_observability()


@app.get("/api/tools/observability/overview")
def api_tools_observability_overview(limit: int = 20):
    from src.tools.observability import get_tools_observability_overview

    return get_tools_observability_overview(limit=limit)


@app.get("/api/tools/observability/calls")
def api_tools_observability_calls(limit: int = 50):
    from src.tools.observability import get_tool_calls_observability

    return get_tool_calls_observability(limit=limit)


@app.get("/api/tools/observability/results")
def api_tools_observability_results(limit: int = 50):
    from src.tools.observability import get_tool_results_observability

    return get_tool_results_observability(limit=limit)


@app.get("/api/tools/observability/audit")
def api_tools_observability_audit(limit: int = 50):
    from src.tools.observability import get_tool_audit_observability

    return get_tool_audit_observability(limit=limit)


@app.get("/api/tools/observability/blocked")
def api_tools_observability_blocked(limit: int = 50):
    from src.tools.observability import get_blocked_tool_observability

    return get_blocked_tool_observability(limit=limit)

@app.get("/api/tools/mcp/providers")
def api_get_mcp_provider_statuses():
    from src.tools.mcp_provider_registry import get_mcp_provider_statuses

    return {"providers": get_mcp_provider_statuses(include_config=False)}


@app.get("/api/tools/mcp/providers/{provider_id}")
def api_get_mcp_provider_status(provider_id: str):
    from src.tools.mcp_provider_registry import get_mcp_provider_status

    status = get_mcp_provider_status(provider_id, include_config=False)
    if status is None:
        raise HTTPException(status_code=404, detail="Unknown MCP provider")
    return status


@app.post("/api/tools/mcp/providers/{provider_id}/discover")
def api_discover_mcp_provider(provider_id: str):
    from src.tools.mcp_provider_registry import get_mcp_provider_status

    status = get_mcp_provider_status(provider_id, refresh=True, include_config=False)
    if status is None:
        raise HTTPException(status_code=404, detail="Unknown MCP provider")
    return status



@app.get("/api/tools/external/providers")
def api_get_external_provider_statuses():
    from src.external_providers.registry import get_external_provider_statuses

    return {"providers": get_external_provider_statuses()}


@app.get("/api/tools/external/providers/{provider_id}")
def api_get_external_provider_status(provider_id: str):
    from src.external_providers.registry import get_external_provider_status

    status = get_external_provider_status(provider_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Unknown external API provider")
    return status

@app.get("/api/tools/personal-os/status")
def api_personal_os_status():
    from src.personal_os.observability import get_personal_os_status

    return get_personal_os_status()


@app.get("/api/tools/personal-os/actions")
def api_personal_os_actions():
    from src.personal_os.observability import get_personal_os_actions

    return {"actions": get_personal_os_actions()}


@app.get("/api/tools/personal-os/audit")
def api_personal_os_audit(limit: int = 50):
    from src.personal_os.observability import get_personal_os_audit

    return get_personal_os_audit(limit=limit)

# --- Tasks Endpoints ---

@app.get("/api/tasks")
def api_get_tasks():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, title, description, status, priority, created_at FROM tasks ORDER BY created_at DESC")
    task_rows = cursor.fetchall()

    cursor.execute("SELECT agent_id, role, instructions, status, created_at FROM sub_agents ORDER BY created_at DESC")
    agent_rows = cursor.fetchall()
    conn.close()

    tasks_list = [dict(r) for r in task_rows]
    sub_agents_list = [dict(r) for r in agent_rows]

    if tasks_list:
        summary_lines = [f"â€¢ [{t['status']}] {t['title']} (Priority: {t.get('priority', 'Medium')})" for t in tasks_list]
        summary_str = "\n".join(summary_lines)
    else:
        summary_str = "No active tasks registered."

    return {
        "tasks": tasks_list,
        "total_tasks": len(tasks_list),
        "tasks_summary": summary_str,
        "sub_agents": sub_agents_list
    }


# --- Scheduled Jobs Endpoints ---

@app.get("/api/tools/cron/schedules")
def api_list_cron_schedules(status: Optional[str] = None, limit: int = 100):
    from src.personal_os.scheduler_service import list_schedules

    return {"schedules": list_schedules(status=status, limit=limit)}


@app.post("/api/tools/cron/schedules")
def api_create_cron_schedule(req: CronScheduleRequest):
    from src.personal_os.scheduler_service import create_tool_schedule

    try:
        result = create_tool_schedule(
            schedule_type=req.schedule_type,
            cron_expression=req.cron_expression,
            run_at=req.run_at,
            timezone=req.timezone or "UTC",
            target_tool_id=req.target_tool_id,
            target_payload=req.target_payload or {},
            missed_run_policy=req.missed_run_policy,
            max_catchup_runs=req.max_catchup_runs,
            created_by=req.created_by or "api",
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "success", **result.to_dict()}


@app.get("/api/tools/cron/schedules/{schedule_id}")
def api_get_cron_schedule(schedule_id: str):
    from src.personal_os.scheduler_store import ToolScheduleRepository

    try:
        schedule = ToolScheduleRepository().get_schedule(schedule_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Schedule not found") from exc
    return {"schedule": schedule.to_dict()}


@app.patch("/api/tools/cron/schedules/{schedule_id}")
def api_update_cron_schedule(schedule_id: str, req: CronSchedulePatchRequest):
    from src.personal_os.scheduler_policy import approval_policy_for_target
    from src.personal_os.scheduler_store import ToolScheduleRepository

    repo = ToolScheduleRepository()
    try:
        current = repo.get_schedule(schedule_id)
        updates = {k: v for k, v in req.model_dump().items() if v is not None}
        target = updates.get("target_tool_id", current.target_tool_id)
        new_policy = approval_policy_for_target(target)
        if current.approval_policy != "approval_required" and new_policy == "approval_required":
            raise HTTPException(status_code=403, detail="Schedule update increases risk and requires approval; denied in T5 compatibility API.")
        if "target_tool_id" in updates:
            updates["approval_policy"] = new_policy
        schedule = repo.update_schedule(schedule_id, updates)
    except HTTPException:
        raise
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Schedule not found") from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "success", "schedule": schedule.to_dict()}


@app.delete("/api/tools/cron/schedules/{schedule_id}")
def api_cancel_cron_schedule(schedule_id: str):
    from src.personal_os.scheduler_store import ToolScheduleRepository

    try:
        schedule = ToolScheduleRepository().cancel_schedule(schedule_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Schedule not found") from exc
    return {"status": "success", "schedule": schedule.to_dict()}


@app.get("/api/tools/cron/runs")
def api_list_cron_runs(schedule_id: Optional[str] = None, status: Optional[str] = None, limit: int = 100):
    from src.personal_os.scheduler_service import list_runs

    return {"runs": list_runs(schedule_id=schedule_id, status=status, limit=limit)}


@app.get("/api/scheduled")
def api_get_scheduled():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, cron_or_timestamp, task_payload, status, created_at FROM scheduled_jobs ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()
    return {"scheduled_jobs": [dict(r) for r in rows]}


@app.post("/api/scheduled")
def api_create_scheduled(req: ScheduledJobRequest):
    res = schedule_job.invoke({
        "cron_or_timestamp": req.cron_or_timestamp,
        "task_payload": req.task_payload
    })
    return {"status": "success", "message": res}


@app.delete("/api/scheduled/{job_id}")
def api_delete_scheduled(job_id: str):
    res = cancel_job.invoke({"job_id": job_id})
    return {"status": "success", "message": res}


# --- System Backup & Maintenance Endpoints ---

@app.get("/api/system/backups")
def api_list_backups():

    from src.personal_os.backup import get_available_backups
    backups = get_available_backups()
    return {"backups": backups, "total_backups": len(backups)}

@app.get("/api/system/health")
def api_get_system_health():
    """Returns runtime system telemetry: DB path, schema version, worker status, and provider readiness flags."""
    from src.config import DB_PATH, validate_integration_environment
    from src.db_migrations import check_db_version
    schema_ver = check_db_version(DB_PATH)
    providers = validate_integration_environment()
    return {
        "status": "HEALTHY",
        "app_name": "ASTRA (Autonomous System for Tasks, Reasoning & Assistance)",
        "database_path": str(DB_PATH),
        "schema_version": schema_ver,
        "worker_status": "RUNNING",
        "providers": providers
    }


# --- Data Inspector Endpoints ---

@app.get("/api/data/tables")
def api_get_data_tables():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name ASC")
    rows = cursor.fetchall()
    conn.close()
    found_tables = [r["name"] for r in rows if r["name"] in ALLOWED_DATA_TABLES]
    return {"tables": found_tables}

@app.get("/api/data/table/{table_name}")
def api_get_table_rows(table_name: str, limit: int = 50):
    if table_name not in ALLOWED_DATA_TABLES:
        raise HTTPException(status_code=400, detail=f"Table '{table_name}' is not allowed or does not exist.")


    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(f"SELECT * FROM {table_name} ORDER BY rowid DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()

    result_rows = [dict(r) for r in rows]
    columns = list(result_rows[0].keys()) if result_rows else []
    return {
        "table": table_name,
        "total_rows": len(result_rows),
        "columns": columns,
        "rows": result_rows
    }

# --- HITL Approvals Endpoints ---


@app.get("/api/approvals")
def api_get_approvals():
    requests = get_all_approval_requests()
    return {"approval_requests": requests}

@app.post("/api/approvals/{request_id}/decision")
def api_approval_decision(request_id: str, req: DecisionRequest):
    if req.decision not in ("APPROVED", "REJECTED"):
        raise HTTPException(status_code=400, detail="Decision must be APPROVED or REJECTED.")

    procedural_link = ProceduralSkillApprovalRepository().get_by_approval_request_id(request_id)
    if procedural_link is not None:
        try:
            processed = process_approval_decision(request_id, req.decision)
            procedural_result = process_procedural_skill_approval_decision(
                approval_request_id=request_id,
                decision=req.decision,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        status = str(req.decision).upper()
        tool_name = str(processed.get("tool_name") or "procedural_skill_promotion")
        message = procedural_result.message or f"Procedural skill approval {status}."
        return {
            "request_id": request_id,
            "status": status,
            "tool_name": tool_name,
            "tool_result": message,
            "response": message,
            "message": message,
            "procedural_skill_approval": procedural_result.to_dict(),
        }

    res = resume_graph_after_approval(request_id=request_id, decision=req.decision)
    return res
# --- System Backup & Restore Endpoints ---

class RestoreRequest(BaseModel):
    backup_path: str

@app.post("/api/system/backup")
def api_system_backup():
    res = export_agent_backup()
    return res

@app.post("/api/system/restore")
def api_system_restore(req: RestoreRequest):
    if not req.backup_path.strip():
        raise HTTPException(status_code=400, detail="backup_path cannot be empty.")
    try:
        res = restore_agent_backup(Path(req.backup_path.strip()))
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Restore failed: {str(e)}")

# --- Integration Capability & Status Endpoints ---

@app.get("/api/integrations/status")
def api_get_integrations_status():
    from src.external_providers.registry import get_external_provider_statuses
    from src.tools.mcp_provider_registry import get_mcp_provider_statuses

    providers = {item["provider_id"]: item for item in get_mcp_provider_statuses(include_config=False)}
    external = {item["provider_id"]: item for item in get_external_provider_statuses()}

    def provider_entry(provider_id: str, name: str) -> Dict[str, Any]:
        status = providers.get(provider_id, {})
        available = status.get("availability_status") == "available"
        return {
            "name": name,
            "status": "MCP_AVAILABLE" if available else "MCP_UNAVAILABLE",
            "mode": "provider_managed_mcp",
            "description": "Provider-managed MCP available" if available else "Provider-managed MCP not configured or unavailable",
            "truthfulness": "PROVIDER_MANAGED_MCP" if available else "UNAVAILABLE",
            "provider_id": provider_id,
        }

    def external_entry(provider_id: str, name: str) -> Dict[str, Any]:
        status = external.get(provider_id, {})
        configured = status.get("availability_status") == "configured"
        return {
            "name": name,
            "status": "API_CONFIGURED" if configured else "API_MISSING_CONFIG",
            "mode": "direct_external_api",
            "description": "Direct API provider configured" if configured else "Direct API provider missing configuration",
            "truthfulness": "DIRECT_API" if configured else "UNAVAILABLE",
            "provider_id": provider_id,
            "credential_status": status.get("credential_status", "unknown"),
            "required_env_vars": status.get("required_env_vars", []),
        }

    return {
        "integrations": {
            "calendar": provider_entry("google_calendar", "Google Calendar MCP"),
            "email_smtp": provider_entry("gmail", "Gmail MCP"),
            "email_imap": provider_entry("gmail", "Gmail MCP"),
            "whatsapp": external_entry("whatsapp_api", "WhatsApp API"),
            "telegram": external_entry("telegram_bot_api", "Telegram Bot API"),
            "search": {
                "name": "Search MCP",
                "status": "MCP_AVAILABLE" if any(providers.get(pid, {}).get("availability_status") == "available" for pid in ("search_tavily", "search_duckduckgo")) else "MCP_UNAVAILABLE",
                "mode": "provider_managed_mcp",
                "description": "Provider-managed search MCP available" if any(providers.get(pid, {}).get("availability_status") == "available" for pid in ("search_tavily", "search_duckduckgo")) else "Provider-managed search MCP not configured or unavailable",
                "truthfulness": "PROVIDER_MANAGED_MCP" if any(providers.get(pid, {}).get("availability_status") == "available" for pid in ("search_tavily", "search_duckduckgo")) else "UNAVAILABLE",
                "provider_id": "search_tavily_or_search_duckduckgo",
            }
        }
    }

# --- Serve Static Frontend Files ---


frontend_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "frontend")
dist_path = os.path.join(frontend_path, "dist")
target_static = dist_path if os.path.exists(dist_path) else frontend_path

if os.path.exists(target_static):
    app.mount("/static", StaticFiles(directory=target_static), name="static")

    @app.get("/")
    def serve_frontend():
        index_file = os.path.join(target_static, "index.html")
        if os.path.exists(index_file):
            from fastapi.responses import FileResponse
            return FileResponse(index_file)
        return {"message": "24x7 Personal Assistant API Backend Online"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.api.server:app", host="0.0.0.0", port=8000, reload=True)
