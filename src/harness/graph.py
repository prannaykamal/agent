import json
import uuid
import logging
import time
from datetime import datetime
from typing import List, Dict, Any, Optional
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from langchain_core.messages import BaseMessage, SystemMessage, AIMessage, HumanMessage, ToolMessage, RemoveMessage

from src.db import get_connection
from src.harness.state import AgentState
from src.memory.soul_loader import load_soul_prompt
from src.memory.short_term import estimate_tokens, log_raw_turn, get_raw_turns
from src.memory.summary_blocks import prepare_short_term_context_for_chat

from src.memory.cognee_memory import get_cognee_memory
from src.memory.events import log_memory_event
from src.memory.jev import get_jev_client

from src.hitl.classifier import classify_tool_risk
from src.hitl.approval_engine import create_approval_request, process_approval_decision, get_approval_request, generate_payload_preview
from src.mcp_gateway.email_send_bind import bind_email_send_args
from src.tools.removed_tools import get_removed_tool_blocked_message, is_removed_tool_name
from src.tools.invocation import invoke_registered_tool
from src.tools.policy import ToolCallerSource, evaluate_tool_policy
from src.tools.registry_types import RiskClass
from src.personal_os.checkpointing import checkpoint
from src.harness.models import get_primary_llm
from src.harness.llm_router import normalize_model_name, normalize_provider, resolve_primary_llm
from src.harness.message_text import message_text
from src.memory.jobs import enqueue_post_turn_memory_jobs

logger = logging.getLogger(__name__)

_ORIGINAL_GET_PRIMARY_LLM = get_primary_llm

def _safe_llm_error(exc: Exception) -> str:
    text = str(exc or "").strip() or type(exc).__name__
    return text.replace("\n", " ")[:400]


def _replace_messages(messages) -> List[BaseMessage]:
    """Replace the full `messages` list. `add_messages` would otherwise append a copy."""
    return [RemoveMessage(id=REMOVE_ALL_MESSAGES), *list(messages or [])]


def _normalize_llm_messages(messages):
    """OpenAI rejects system messages after the first user/assistant turn."""
    systems: List[str] = []
    rest: List[BaseMessage] = []
    for message in messages or []:
        if isinstance(message, RemoveMessage):
            continue
        if isinstance(message, SystemMessage):
            content = str(message.content or "").strip()
            if content and content not in systems:
                systems.append(content)
            continue
        rest.append(message)
    if not rest:
        return [SystemMessage(content="\n\n".join(systems))] if systems else []
    if systems:
        return [SystemMessage(content="\n\n".join(systems)), *rest]
    return rest


def _tool_call_id(call: Any) -> str:
    if isinstance(call, dict):
        return str(call.get("id") or "")
    return str(getattr(call, "id", "") or "")


def _message_tool_calls(message) -> List[Any]:
    return list(getattr(message, "tool_calls", None) or [])


def _last_ai_with_tool_calls(messages) -> Optional[AIMessage]:
    for message in reversed(messages or []):
        if isinstance(message, AIMessage) and _message_tool_calls(message):
            return message
    return None


def _in_flight_tool_tail(messages) -> List[BaseMessage]:
    """Keep a trailing assistant tool_calls + tool-result pair across memory rebuilds."""
    msgs = list(messages or [])
    tool_msgs: List[ToolMessage] = []
    idx = len(msgs) - 1
    while idx >= 0 and isinstance(msgs[idx], ToolMessage):
        tool_msgs.append(msgs[idx])
        idx -= 1
    tool_msgs.reverse()
    if not tool_msgs:
        return []
    lead = msgs[idx] if idx >= 0 else None
    if isinstance(lead, AIMessage) and _message_tool_calls(lead):
        return [lead, *tool_msgs]
    return []


def _sanitize_llm_messages(messages):
    """Drop orphan tool results and unpaired tool_calls before calling the model.

    OpenAI rejects any `role: tool` message that does not immediately follow an
    assistant message with `tool_calls`. Chat history rebuilds and HITL pauses
    can leave the list in that illegal shape.
    """
    normalized = _normalize_llm_messages(messages)
    sanitized: List[BaseMessage] = []
    index = 0
    while index < len(normalized):
        message = normalized[index]
        if isinstance(message, ToolMessage):
            index += 1
            continue
        tool_calls = _message_tool_calls(message) if isinstance(message, AIMessage) else []
        if isinstance(message, AIMessage) and tool_calls:
            expected_ids = {cid for cid in (_tool_call_id(call) for call in tool_calls) if cid}
            cursor = index + 1
            matched: List[ToolMessage] = []
            found_ids = set()
            while cursor < len(normalized) and isinstance(normalized[cursor], ToolMessage):
                tool_message = normalized[cursor]
                tool_call_id = str(getattr(tool_message, "tool_call_id", "") or "")
                if tool_call_id in expected_ids and tool_call_id not in found_ids:
                    matched.append(tool_message)
                    found_ids.add(tool_call_id)
                cursor += 1
            if expected_ids and expected_ids <= found_ids:
                sanitized.append(message)
                sanitized.extend(matched)
                index = cursor
                continue
            content = str(message.content or "").strip()
            sanitized.append(AIMessage(content=content or "Continuing."))
            index += 1
            continue
        sanitized.append(message)
        index += 1
    return sanitized


def _offline_ai_message(messages, provider, model_name, hint):
    last_user_msg = next((m.content for m in reversed(messages) if isinstance(m, HumanMessage)), "Hello")
    return AIMessage(
        content=(
            f"[{provider.capitalize()}/{model_name} Primary LLM (Offline)]: Processed request -> '{last_user_msg}'\n\n"
            f"{hint}"
        )
    )


def get_registered_tools():
    """Lazily fetches and maps bindable local, MCP, and direct external API tools."""
    from src.personal_os.registry import get_all_personal_os_tools
    from src.mcp_gateway.registry import get_all_external_api_tools, get_all_mcp_tools

    tools = get_all_personal_os_tools() + get_all_mcp_tools() + get_all_external_api_tools()
    tool_map = {t.name: t for t in tools}
    return tools, tool_map


_TOOL_GUIDANCE_MARKER = "When a user request matches a bound tool"


def _tool_use_guidance(tools) -> str:
    names = {getattr(tool, "name", "") for tool in tools}
    lines = [
        f"{_TOOL_GUIDANCE_MARKER}, you MUST call that tool instead of describing manual steps.",
    ]
    if "email_draft" in names:
        lines.append("For Gmail drafts, call email_draft(to, subject, body). Do not give Gmail website instructions.")
    if "email_send" in names:
        lines.append(
            "When the user asks to send email, or replies yes/send it/go ahead after discussing an email, "
            "you MUST call email_send(to, subject, body) in that same turn. Do not ask the user to confirm in chat. "
            "After email_draft, copy the exact recipient, subject, and body from that draft tool result. "
            "Never invent addresses like name@example.com or placeholder signatures like [Your Name]. "
            "Do not mention safety protocols or extra authorization. HITL is handled by the system after the tool call. "
            "Never say an email was sent unless email_send returned a Sent result."
        )
    if "email_read" in names:
        lines.append("email_read lists recent Gmail Inbox mail. Use email_search for Sent or other folders.")
    if "search_web" in names:
        lines.append("For web search, call search_web.")
    if "telegram_read" in names:
        lines.append("telegram_read fetches live bot updates. telegram_send sends a message.")
    if "whatsapp_read" in names:
        lines.append("whatsapp_read lists stored WhatsApp inbox messages (webhook-backed). whatsapp_send sends a message.")
    if "schedule_job" in names:
        lines.append(
            'For reminders, call schedule_job with a time and a payload. '
            'Use JSON {"tool":"create_task","args":{"title":"..."}} to run a specific tool, '
            "or a reminder string which creates a task when due."
        )
    calendar_tools = names & {"calendar_create_event", "calendar_inspect_availability", "calendar_update_event", "calendar_delete_event"}
    if calendar_tools:
        now = datetime.now().astimezone()
        lines.append(
            f"Today is {now.strftime('%A, %Y-%m-%d')} in the user's local timezone. "
            "For calendar writes, call calendar_create_event(title, start_time, end_time) using ISO datetimes "
            f"such as {now.strftime('%Y-%m-%d')}T17:00:00. Never use a past year such as 2023. "
            "If the user omits an end time, use a 1 hour duration."
        )
    lines.append(
        "If retrieved long-term memory is present, use those stored facts instead of inventing missing details."
    )
    lines.append(
        "If a tool result says Human-In-The-Loop approval is required, summarize what you already learned "
        "for the user and wait. Do not retry that high-risk tool in the same turn."
    )
    return " ".join(lines)


def _messages_with_tool_guidance(messages, tools):
    guidance = _tool_use_guidance(tools)
    updated = list(messages)
    for index, message in enumerate(updated):
        if not isinstance(message, SystemMessage):
            continue
        content = str(message.content or "")
        if _TOOL_GUIDANCE_MARKER in content:
            return updated
        updated[index] = SystemMessage(content=f"{content}\n\n{guidance}")
        return updated
    return [SystemMessage(content=guidance)] + updated


def _log_removed_tool_block(session_id: str, tool_name: str, tool_args: Any, details: str) -> None:
    try:
        from src.hitl.audit_logger import log_audit_event
        log_audit_event(
            session_id=session_id,
            tool_name=tool_name,
            risk_level="Blocked",
            action="REMOVED_TOOL_BLOCKED",
            tool_args=tool_args if isinstance(tool_args, dict) else {},
            details=details[:500],
        )
    except Exception:
        pass

def log_loop_event(session_id: str, step_index: int, step_type: str, reasoning: str = "", tool_name: str = "", tool_args: Any = None, tool_result: str = "") -> Dict[str, Any]:
    """Logs a loop step event into SQLite loop_events, tool_calls, and tool_results tables."""
    event_id = f"evt_{uuid.uuid4().hex[:8]}"
    args_json = json.dumps(tool_args) if tool_args else ""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO loop_events (id, session_id, step_index, step_type, reasoning, tool_name, tool_args_json, tool_result, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        """,
        (event_id, session_id, step_index, step_type, reasoning, tool_name, args_json, tool_result)
    )

    if step_type == "TOOL_REQUESTED":
        cursor.execute(
            "INSERT INTO tool_calls (id, session_id, tool_name, tool_args, status, created_at) VALUES (?, ?, ?, ?, 'REQUESTED', datetime('now'))",
            (event_id, session_id, tool_name, args_json)
        )
    elif step_type == "TOOL_EXECUTED":
        cursor.execute(
            "INSERT INTO tool_results (id, tool_call_id, session_id, tool_name, result_content, status, created_at) VALUES (?, ?, ?, ?, ?, 'SUCCESS', datetime('now'))",
            (f"res_{uuid.uuid4().hex[:8]}", event_id, session_id, tool_name, tool_result)
        )

    conn.commit()
    conn.close()
    event = {
        "id": event_id,
        "step_index": step_index,
        "step_type": step_type,
        "reasoning": reasoning,
        "tool_name": tool_name,
        "tool_args": tool_args,
        "tool_result": tool_result,
        "session_id": session_id,
    }
    try:
        from src.harness.loop_stream import publish

        publish({"type": "step", **event}, session_id=session_id)
    except Exception:
        pass
    return event


def node_ingest(state: AgentState) -> dict:
    """Node: Ensures SOUL system prompt is present in message history and logs raw user turn."""
    messages = list(state.get("messages", []))
    session_id = state.get("session_id", "default_session")
    events = list(state.get("loop_events") or [])
    soul_prompt = load_soul_prompt()

    has_system_prompt = any(isinstance(m, SystemMessage) for m in messages)
    if not has_system_prompt:
        messages = [soul_prompt] + messages

    # Resume-after-approval re-invokes the full graph; do not duplicate the user turn.
    is_approval_resume = state.get("approval_status") in ("APPROVED", "REJECTED")
    last_user_msg = next((m.content for m in reversed(messages) if isinstance(m, HumanMessage)), None)
    if last_user_msg and not is_approval_resume:
        log_raw_turn(session_id=session_id, sender="user", content=str(last_user_msg))
        evt = log_loop_event(
            session_id=session_id,
            step_index=0,
            step_type="USER_INPUT",
            reasoning=f"Ingested user message: '{last_user_msg}'"
        )
        events.append(evt)

    return {
        "messages": _replace_messages(messages),
        "token_count": estimate_tokens(messages),
        "loop_count": 0,
        "tools_used": [],
        "loop_events": events
    }

def _primary_selection(state: AgentState) -> tuple:
    """Provider/model for this turn; missing values follow AI_PROVIDER's profile."""
    provider = normalize_provider(state.get("provider"))
    return provider, normalize_model_name(provider, state.get("model_name"), "primary")


def node_manage_memory(state: AgentState) -> dict:
    """Node: Reconstructs short-term context from immutable summary blocks and raw turns."""
    messages = list(state.get("messages", []))
    session_id = state.get("session_id", "default_session")

    provider, model_name = _primary_selection(state)
    context = prepare_short_term_context_for_chat(
        session_id=session_id,
        current_messages=messages,
        provider=provider,
        model_name=model_name,
        secondary_provider=state.get("secondary_provider"),
        secondary_model_name=state.get("secondary_model_name"),
    )

    reconstructed = list(context.messages)
    tail = _in_flight_tool_tail(messages)
    if tail:
        reconstructed.extend(tail)

    return {
        "messages": _replace_messages(reconstructed),
        "summary": "",
        "token_count": estimate_tokens(reconstructed),
        "trimming_occurred": bool(context.omitted_unsummarized_turn_ids),
        "summary_status": context.status,
        "pending_summary_job_id": context.pending_summary_job_id,
    }

def _previous_assistant_text(messages) -> str:
    """The assistant reply just before the latest user message (context for short follow-ups)."""
    seen_user = False
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            seen_user = True
        elif seen_user and isinstance(message, AIMessage) and message_text(message):
            return message_text(message)
    return ""


def _error_category(error: Optional[str]) -> Optional[str]:
    return error.split(":", 1)[0] if error else None


def node_memory_router(state: AgentState) -> dict:
    """Node: asks Jev whether to store/retrieve, and injects main-graph memory only when retrieval is needed.

    Short-term context (trimming + summaries) is handled earlier by manage_memory
    and is never replaced by cognee.
    """
    messages = list(state.get("messages", []))
    session_id = state.get("session_id", "default_session")
    last_user_msg = next((m.content for m in reversed(messages) if isinstance(m, HumanMessage)), "")
    result = {
        "messages": _replace_messages(messages),
        "retrieval_triggered": False,
        "retrieved_memories": [],
        "memory_storage_decision": None,
        "memory_retrieval_decision": None,
    }

    # Approval resumes replay a turn that was already routed; no new user query, no Jev call.
    if state.get("approval_status") in ("APPROVED", "REJECTED") or not last_user_msg:
        return result

    memory = get_cognee_memory()
    config = memory.config
    if not config.enabled or not (config.storage_enabled or config.retrieval_enabled):
        return result

    user_id = state.get("user_id") or config.user_id
    query = str(last_user_msg)
    decision = get_jev_client().decide_memory(query, _previous_assistant_text(messages))
    should_store = decision.should_store and config.storage_enabled
    should_retrieve = decision.should_retrieve and config.retrieval_enabled
    common = {
        "user_id": user_id,
        "session_id": session_id,
        "source": decision.source,
        "latency_ms": decision.latency_ms,
        "error_category": decision.error_category,
    }
    log_memory_event("memory.store.decision", decision=should_store, **common)
    log_memory_event("memory.retrieve.decision", decision=should_retrieve, **common)
    result["memory_storage_decision"] = {**decision.to_state(), "should_store": should_store}
    result["memory_retrieval_decision"] = {**decision.to_state(), "should_retrieve": should_retrieve}
    if not should_retrieve:
        return result

    log_loop_event(
        session_id=session_id,
        step_index=0,
        step_type="RETRIEVAL",
        reasoning="Searching long-term memory",
    )
    started = time.monotonic()
    try:
        recalled = memory.recall(query, user_id=user_id)
    except Exception:
        logger.exception("Long-term memory recall failed")
        log_memory_event("memory.retrieve", user_id=user_id, session_id=session_id, success=False, error_category="unexpected")
        return result
    log_memory_event(
        "memory.retrieve",
        user_id=user_id,
        session_id=session_id,
        success=recalled.available and recalled.error is None,
        hits=len(recalled.memories),
        latency_ms=int((time.monotonic() - started) * 1000),
        error_category=_error_category(recalled.error),
    )

    # Skip snippets the current conversation already contains.
    active_context = "\n".join(message_text(m) for m in messages if not isinstance(m, SystemMessage))
    fresh = recalled.without_known(active_context)
    block = fresh.to_context_block(config.retrieval_token_budget)
    if not block:
        return result
    messages.append(SystemMessage(content=block))
    return {
        **result,
        "messages": _replace_messages(messages),
        "retrieval_triggered": True,
        "retrieved_memories": [item.to_dict() for item in fresh.memories],
    }

def node_agent(state: AgentState) -> dict:
    """Node: Invokes Primary LLM bound with tools and advances loop step."""
    if state.get("approval_status") == "PENDING":
        messages = list(state.get("messages") or [])
        has_tool_observation = any(isinstance(message, ToolMessage) for message in messages)
        if not has_tool_observation:
            return {}

    messages = list(state.get("messages", []))
    session_id = state.get("session_id", "default_session")
    provider, model_name = _primary_selection(state)
    loop_count = (state.get("loop_count") or 0) + 1
    events = list(state.get("loop_events") or [])
    tools_used = list(state.get("tools_used") or [])

    tools, _ = get_registered_tools()
    messages = _sanitize_llm_messages(_messages_with_tool_guidance(messages, tools))
    evt_llm = log_loop_event(
        session_id=session_id,
        step_index=loop_count,
        step_type="LLM_STARTED",
        reasoning=f"Thinking with {provider}/{model_name}",
    )
    events.append(evt_llm)
    primary_route = resolve_primary_llm(provider=provider, model_name=model_name)
    provider = primary_route.selector.provider
    model_name = primary_route.selector.model_name

    # Tests inject DeterministicFakeLLM via get_primary_llm. Honor that even when
    # a real API key is present in the local .env.
    if get_primary_llm is not _ORIGINAL_GET_PRIMARY_LLM:
        llm, _ = get_primary_llm(provider=provider, model_name=model_name)
    else:
        llm = primary_route.llm

    response = None
    if llm and hasattr(llm, "bind_tools"):
        try:
            response = llm.bind_tools(tools).invoke(messages)
        except Exception as exc:
            response = _offline_ai_message(
                messages,
                provider,
                model_name,
                f"Model call failed: {_safe_llm_error(exc)}",
            )
    if response is None:
        env_key = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "gemini": "GOOGLE_API_KEY",
            "grok": "XAI_API_KEY",
        }.get(provider, "API_KEY")
        hint = primary_route.error or f"No usable {env_key}. Add it to .env and restart the backend."
        response = _offline_ai_message(messages, provider, model_name, hint)

    response = _bind_email_send_on_response(response, messages, session_id)
    tool_calls = getattr(response, "tool_calls", []) or []

    if tool_calls:
        evt_reasoning = log_loop_event(
            session_id=session_id,
            step_index=loop_count,
            step_type="REASONING",
            reasoning=message_text(response) if message_text(response) else f"Decided to invoke tool(s): {', '.join([tc['name'] for tc in tool_calls])}"
        )
        events.append(evt_reasoning)

        for tc in tool_calls:
            evt_tool_req = log_loop_event(
                session_id=session_id,
                step_index=loop_count,
                step_type="TOOL_REQUESTED",
                tool_name=tc["name"],
                tool_args=tc.get("args", {}),
                reasoning=f"Proposed tool execution: '{tc['name']}'"
            )
            events.append(evt_tool_req)
    else:
        evt_final = log_loop_event(
            session_id=session_id,
            step_index=loop_count,
            step_type="FINAL_RESPONSE",
            reasoning=message_text(response) or "[Final Response Generated]"
        )
        events.append(evt_final)

    # Log raw assistant response turn uncompacted
    if response and message_text(response):
        log_raw_turn(session_id=session_id, sender="assistant", content=message_text(response))

    return {
        "messages": [response],
        "loop_count": loop_count,
        "loop_events": events,
        "tools_used": tools_used
    }

def _tool_call_name(call: Any) -> str:
    if isinstance(call, dict):
        return str(call.get("name") or "")
    return str(getattr(call, "name", "") or "")


def _tool_call_args(call: Any) -> Dict[str, Any]:
    if isinstance(call, dict):
        return dict(call.get("args") or {})
    return dict(getattr(call, "args", None) or {})


def _last_user_text(messages) -> str:
    return next((str(m.content) for m in reversed(messages or []) if isinstance(m, HumanMessage)), "")


def _bind_email_send_call(call: Any, messages, session_id: str) -> Any:
    if _tool_call_name(call) != "email_send":
        return call
    bound_args = bind_email_send_args(
        _tool_call_args(call),
        messages=messages,
        last_user_text=_last_user_text(messages),
        session_id=session_id,
    )
    if bound_args == _tool_call_args(call):
        return call
    if isinstance(call, dict):
        updated = dict(call)
        updated["args"] = bound_args
        return updated
    return {
        "name": "email_send",
        "args": bound_args,
        "id": _tool_call_id(call) or f"call_{uuid.uuid4().hex[:6]}",
    }


def _bind_email_send_on_response(response, messages, session_id: str):
    tool_calls = getattr(response, "tool_calls", None) or []
    if not any(_tool_call_name(call) == "email_send" for call in tool_calls):
        return response
    bound_calls = [_bind_email_send_call(call, messages, session_id) for call in tool_calls]
    if bound_calls == list(tool_calls):
        return response
    return AIMessage(content=getattr(response, "content", "") or "", tool_calls=bound_calls)


_INTERNAL_TOOL_ARG_KEYS = frozenset({"_tool_call_id", "_batch_calls"})


def _public_tool_args(tool_args: Any) -> Dict[str, Any]:
    if not isinstance(tool_args, dict):
        return {}
    return {key: value for key, value in tool_args.items() if key not in _INTERNAL_TOOL_ARG_KEYS}


def _normalize_tool_call(call: Any) -> Dict[str, Any]:
    return {
        "name": _tool_call_name(call),
        "args": _public_tool_args(_tool_call_args(call)),
        "id": _tool_call_id(call) or f"call_{uuid.uuid4().hex[:6]}",
    }


def _same_tool_high_risk_batch(tool_calls, primary_name: str) -> List[Dict[str, Any]]:
    """Same-turn high-risk siblings of one tool; one HITL approval covers the batch."""
    batch: List[Dict[str, Any]] = []
    for call in tool_calls or []:
        name = _tool_call_name(call)
        if name != primary_name:
            continue
        if classify_tool_risk(name)[0] != "High":
            continue
        batch.append(_normalize_tool_call(call))
    return batch


def _parse_approved_tool_batch(tool_name: str, tool_args: Any) -> List[Dict[str, Any]]:
    payload = dict(tool_args) if isinstance(tool_args, dict) else {}
    raw_batch = payload.pop("_batch_calls", None)
    fallback_id = str(payload.pop("_tool_call_id", "") or f"call_{uuid.uuid4().hex[:6]}")
    public_args = _public_tool_args(payload)
    batch: List[Dict[str, Any]] = []
    if isinstance(raw_batch, list):
        for item in raw_batch:
            if not isinstance(item, dict):
                continue
            batch.append({
                "name": str(item.get("name") or tool_name),
                "args": _public_tool_args(item.get("args")),
                "id": str(item.get("id") or f"call_{uuid.uuid4().hex[:6]}"),
            })
    if not batch:
        batch = [{"name": tool_name, "args": public_args, "id": fallback_id}]
    return batch


def _first_high_risk_tool_call(tool_calls):
    for call in tool_calls or []:
        name = _tool_call_name(call)
        risk_level, reason = classify_tool_risk(name)
        if risk_level == "High":
            return call, reason
    return None, ""


def _has_non_high_tool_call(tool_calls) -> bool:
    for call in tool_calls or []:
        name = _tool_call_name(call)
        if classify_tool_risk(name)[0] != "High":
            return True
    return False


def _pause_for_high_risk_tool(
    session_id: str,
    call: Any,
    reason: str,
    events: List[Dict[str, Any]],
    last_user_text: str = "",
    sibling_calls: Optional[List[Any]] = None,
    messages: Optional[List[Any]] = None,
) -> dict:
    call = _bind_email_send_call(call, messages or [], session_id)
    detected_tool = _tool_call_name(call)
    tool_args = _tool_call_args(call)
    tool_call_id = _tool_call_id(call) or f"call_{uuid.uuid4().hex[:6]}"
    batch = [_normalize_tool_call(_bind_email_send_call(item, messages or [], session_id)) for item in (sibling_calls or [call])]
    if not batch:
        batch = [_normalize_tool_call(call)]

    chk_res = checkpoint.invoke({"task_id": session_id})
    checkpoint_id = chk_res.split("ID '")[1].split("' for task")[0] if "ID '" in chk_res else ""
    saved_args = dict(tool_args or {"input": last_user_text})
    saved_args["_tool_call_id"] = tool_call_id
    if len(batch) > 1:
        saved_args["_batch_calls"] = batch
    app_req = create_approval_request(
        session_id=session_id,
        tool_name=detected_tool,
        tool_args=saved_args,
        reason=reason,
        checkpoint_id=checkpoint_id,
    )
    events.append(
        log_loop_event(
            session_id=session_id,
            step_index=98,
            step_type="HITL_REQUIRED",
            tool_name=detected_tool,
            tool_args=tool_args,
            reasoning=(
                f"High risk action '{detected_tool}' requires human approval. Reason: {reason}"
                + (f" Batch size: {len(batch)}." if len(batch) > 1 else "")
            ),
        )
    )
    batch_note = ""
    if len(batch) > 1:
        batch_note = f"This approval covers {len(batch)} '{detected_tool}' actions from this turn.\n"
    pause_msg = AIMessage(
        content=(
            f"[HUMAN APPROVAL REQUIRED - HIGH RISK TASK]\n"
            f"Tool Requested: {detected_tool}\n"
            f"{batch_note}"
            f"Risk Justification: {reason}\n"
            f"{generate_payload_preview(detected_tool, saved_args)}\n"
            f"Approval Request ID: {app_req['request_id']}\n"
            f"Reply yes in this chat to approve, or open Approvals to reject."
        )
    )
    return {
        "messages": [pause_msg],
        "pending_approval_id": app_req["request_id"],
        "approval_status": "PENDING",
        "loop_events": events,
    }


def node_hitl_check(state: AgentState) -> dict:
    """
    Node: Evaluates tool call risk. If High Risk operation is detected,
    creates state checkpoint, generates approval request, and interrupts loop.
    """
    messages = state.get("messages", [])
    session_id = state.get("session_id", "default_session")
    events = list(state.get("loop_events") or [])
    last_msg = messages[-1] if messages else None

    tool_calls = getattr(last_msg, "tool_calls", []) if last_msg else []
    last_user_text = next((str(m.content) for m in reversed(messages) if isinstance(m, HumanMessage)), "").lower()

    high_call, reason = _first_high_risk_tool_call(tool_calls)
    if high_call is not None and not _has_non_high_tool_call(tool_calls):
        batch = _same_tool_high_risk_batch(tool_calls, _tool_call_name(high_call))
        return _pause_for_high_risk_tool(
            session_id,
            high_call,
            reason,
            events,
            last_user_text,
            sibling_calls=batch,
            messages=messages,
        )

    return {"pending_approval_id": None, "approval_status": "NONE"}

def _jev_tool_escalation(session_id: str, tool_name: str, tool_args: Dict[str, Any], messages) -> Optional[str]:
    """Ask Jev whether a call that policy would run directly should go to HITL instead.

    Escalation only: Jev is consulted for medium-risk or confirmation-recommended
    calls that would otherwise execute without approval. It can add an approval
    step but never removes one, and any Jev failure keeps the policy outcome.
    """
    jev = get_jev_client()
    if not (jev.config.tool_review_enabled and jev.available):
        return None
    policy = evaluate_tool_policy(tool_name, tool_args, source=ToolCallerSource.CHAT, approval_context={"approved": False})
    if policy.blocked or policy.unavailable or policy.requires_approval:
        return None
    if policy.risk_class != RiskClass.MEDIUM and policy.reason_code != "confirmation_recommended":
        return None
    user_request = next((str(m.content) for m in reversed(messages) if isinstance(m, HumanMessage)), "")
    route = jev.review_tool_call(
        user_request=user_request,
        tool_name=tool_name,
        tool_args=tool_args,
        policy_reason=policy.reason,
    )
    log_memory_event(
        "tool.route.decision",
        session_id=session_id,
        tool_name=tool_name,
        risk_class=policy.risk_class.value,
        requires_approval=route.requires_approval,
        source=route.source,
        latency_ms=route.latency_ms,
        error_category=route.error_category,
    )
    if not route.requires_approval:
        return None
    return f"Jev review flagged this call for approval: {route.reason or 'it may not match your request'}"


def node_tools(state: AgentState) -> dict:
    """Node: Executes requested tool calls, records observations, and updates loop events."""
    messages = list(state.get("messages", []))
    session_id = state.get("session_id", "default_session")
    loop_count = state.get("loop_count", 1)
    events = list(state.get("loop_events") or [])
    tools_used = list(state.get("tools_used") or [])
    approval_status = state.get("approval_status")

    _, tool_map = get_registered_tools()
    if approval_status == "PENDING":
        return {"tools_used": tools_used, "loop_events": events}

    last_ai = _last_ai_with_tool_calls(messages)
    tool_calls = _message_tool_calls(last_ai) if last_ai is not None else []

    tool_messages = []
    hitl_pause = None
    for call in tool_calls:
        tname = call["name"]
        targs = _tool_call_args(_bind_email_send_call(call, messages, session_id))
        tcall_id = call.get("id", f"call_{uuid.uuid4().hex[:6]}")

        escalation = None
        if approval_status != "APPROVED" and hitl_pause is None:
            escalation = _jev_tool_escalation(session_id, tname, targs, messages)
        if escalation is not None:
            last_user_text = next((str(m.content) for m in reversed(messages) if isinstance(m, HumanMessage)), "")
            hitl_pause = _pause_for_high_risk_tool(
                session_id,
                {"name": tname, "args": targs, "id": tcall_id},
                escalation,
                events,
                last_user_text,
                messages=messages,
            )
            held = f"Not executed: '{tname}' is waiting for human approval. {escalation}"
            events.append(
                log_loop_event(
                    session_id=session_id,
                    step_index=loop_count,
                    step_type="OBSERVATION",
                    tool_name=tname,
                    tool_args=targs,
                    tool_result=held,
                )
            )
            tool_messages.append(ToolMessage(content=held, tool_call_id=tcall_id, name=tname))
            continue

        invocation = invoke_registered_tool(
            tname,
            targs,
            tool_map,
            source=ToolCallerSource.CHAT,
            approval_context={"approved": approval_status == "APPROVED"},
        )
        policy_decision = invocation.policy_decision
        risk_level = policy_decision.risk_class.value if policy_decision else "Blocked"
        result_str = invocation.to_text()

        if policy_decision and policy_decision.reason_code == "removed_tool":
            _log_removed_tool_block(session_id, tname, targs, result_str)

        if (
            hitl_pause is None
            and policy_decision
            and policy_decision.requires_approval
            and approval_status != "APPROVED"
        ):
            last_user_text = next((str(m.content) for m in reversed(messages) if isinstance(m, HumanMessage)), "")
            hitl_pause = _pause_for_high_risk_tool(
                session_id,
                {"name": tname, "args": targs, "id": tcall_id},
                policy_decision.reason,
                events,
                last_user_text,
                sibling_calls=_same_tool_high_risk_batch(tool_calls, tname),
                messages=messages,
            )

        attempted_nonblocked_tool = policy_decision and not policy_decision.blocked and not policy_decision.requires_approval
        if (invocation.ok or attempted_nonblocked_tool) and tname not in tools_used:
            tools_used.append(tname)
        if risk_level in ("Medium", "High", "Blocked"):
            try:
                from src.hitl.audit_logger import log_audit_event
                log_audit_event(
                    session_id=session_id,
                    tool_name=tname,
                    risk_level=risk_level,
                    action="TOOL_EXECUTED" if approval_status == "APPROVED" or risk_level == "Medium" else "TOOL_BLOCKED",
                    tool_args=targs,
                    details=result_str[:200]
                )
            except Exception:
                pass

        # Store in formal tool_calls and tool_results tracking tables
        try:
            from src.db import get_connection
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO tool_calls (id, session_id, tool_name, tool_args, status, created_at) VALUES (?, ?, ?, ?, 'EXECUTED', datetime('now'))",
                (tcall_id, session_id, tname, json.dumps(targs))
            )
            cursor.execute(
                "INSERT INTO tool_results (id, tool_call_id, session_id, tool_name, result_content, status, created_at) VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
                (f"res_{uuid.uuid4().hex[:8]}", tcall_id, session_id, tname, result_str, "SUCCESS" if "error" not in result_str.lower() and "blocked" not in result_str.lower() else "FAILED")
            )
            conn.commit()
            conn.close()
        except Exception:
            pass

        evt_exec = log_loop_event(
            session_id=session_id,
            step_index=loop_count,
            step_type="TOOL_EXECUTED",
            tool_name=tname,
            tool_args=targs,
            tool_result=result_str
        )

        events.append(evt_exec)

        evt_obs = log_loop_event(
            session_id=session_id,
            step_index=loop_count,
            step_type="OBSERVATION",
            tool_name=tname,
            tool_args=targs,
            tool_result=result_str
        )
        events.append(evt_obs)

        tool_messages.append(ToolMessage(content=result_str, tool_call_id=tcall_id, name=tname))

    result = {
        "messages": tool_messages,
        "tools_used": tools_used,
        "loop_events": events,
    }
    if hitl_pause:
        result["pending_approval_id"] = hitl_pause["pending_approval_id"]
        result["approval_status"] = "PENDING"
        result["loop_events"] = hitl_pause.get("loop_events") or events
    return result

def node_consolidate(state: AgentState) -> dict:
    """Node: Enqueues durable memory jobs after completed turns without executing them."""
    if state.get("approval_status") in ("PENDING", "REJECTED"):
        return {"memory_job_ids": []}

    try:
        results = enqueue_post_turn_memory_jobs(state)
        return {"memory_job_ids": [result.job_id for result in results]}
    except Exception:
        return {"memory_job_ids": []}

def should_continue(state: AgentState) -> str:
    """Conditional Edge: Determines whether to loop tool execution, pause for HITL, or end turn."""
    if state.get("approval_status") == "PENDING":
        return "end"

    loop_count = state.get("loop_count", 0)
    messages = state.get("messages", [])
    last_msg = messages[-1] if messages else None
    tool_calls = getattr(last_msg, "tool_calls", []) if last_msg else []

    if loop_count >= 10:
        return "consolidate"

    if tool_calls:
        if state.get("approval_status") == "APPROVED":
            return "consolidate"
        return "hitl_check"

    return "consolidate"


def route_after_hitl(state: AgentState) -> str:
    """High-risk pauses must not continue into tool execution."""
    if state.get("approval_status") == "PENDING":
        return "end"
    return "tools"


_APPROVAL_STALL_MARKERS = (
    "additional approval",
    "safety protocols",
    "cannot proceed",
    "without that approval",
    "requires approval",
    "human approval required",
    "i cannot proceed",
    "unable to send",
)


def _resume_user_response(messages, tool_output: str) -> str:
    """Prefer a real send/result over the model asking for approval again."""
    llm_text = next(
        (message_text(m) for m in reversed(messages or []) if isinstance(m, AIMessage) and message_text(m)),
        "",
    )
    lowered = llm_text.lower()
    if llm_text and not any(marker in lowered for marker in _APPROVAL_STALL_MARKERS):
        return llm_text
    return str(tool_output or llm_text or "").strip()


def _already_processed_approval_response(request_id: str, existing_request: Dict[str, Any], existing_status: str) -> Dict[str, Any]:
    status = "APPROVED" if existing_status == "EXECUTED" else existing_status
    tool_name = str((existing_request or {}).get("tool_name") or "")
    message = (
        f"Approval request '{request_id}' was already {status}. "
        "Duplicate execution skipped."
    )
    return {
        "request_id": request_id,
        "status": status,
        "tool_name": tool_name,
        "tool_result": message,
        "response": message,
        "message": message,
    }


def resume_graph_after_approval(request_id: str, decision: str) -> Dict[str, Any]:
    """Resumes or aborts graph execution after human approval decision ('APPROVED' or 'REJECTED'). Preserves full conversation state."""
    existing_request = get_approval_request(request_id)
    if existing_request is None:
        raise ValueError(f"Approval request '{request_id}' not found.")
    existing_tool_name = str(existing_request.get("tool_name") or "")
    existing_status = str(existing_request.get("status") or "").upper()
    norm_decision = str(decision or "").upper().strip()
    if existing_status in ("APPROVED", "REJECTED", "EXECUTED"):
        same_decision = (
            (norm_decision == "APPROVED" and existing_status in ("APPROVED", "EXECUTED"))
            or (norm_decision == "REJECTED" and existing_status == "REJECTED")
        )
        if same_decision:
            return _already_processed_approval_response(request_id, existing_request, existing_status)
        raise ValueError(
            f"Approval request '{request_id}' has already been processed with status '{existing_status}'. Duplicate execution blocked."
        )
    if norm_decision == "APPROVED" and is_removed_tool_name(existing_tool_name):
        blocked_message = get_removed_tool_blocked_message(existing_tool_name)
        try:
            processed = process_approval_decision(request_id, "REJECTED")
        except Exception:
            processed = existing_request or {"tool_name": existing_tool_name, "session_id": "default_session"}
        session_id = processed.get("session_id", "default_session")
        raw_args = processed.get("tool_args_json", "{}")
        try:
            tool_args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
        except Exception:
            tool_args = {}
        _log_removed_tool_block(session_id, existing_tool_name, tool_args, blocked_message)
        log_loop_event(
            session_id=session_id,
            step_index=99,
            step_type="HITL_BLOCKED",
            reasoning=f"Approval resume blocked removed tool '{existing_tool_name}'",
            tool_name=existing_tool_name,
            tool_args=tool_args,
            tool_result=blocked_message,
        )
        return {
            "request_id": request_id,
            "status": "BLOCKED",
            "tool_name": existing_tool_name,
            "tool_result": blocked_message,
            "response": blocked_message,
            "message": blocked_message,
        }

    if str(decision or "").upper().strip() == "APPROVED":
        raw_existing_args = (existing_request or {}).get("tool_args_json", "{}")
        try:
            existing_tool_args = json.loads(raw_existing_args) if isinstance(raw_existing_args, str) else raw_existing_args
        except Exception:
            existing_tool_args = {}
        policy_args = _public_tool_args(existing_tool_args)
        preflight = evaluate_tool_policy(
            existing_tool_name,
            policy_args,
            source=ToolCallerSource.APPROVAL_RESUME,
            approval_context={"approved": True, "request_id": request_id},
        )
        if preflight.blocked or preflight.unavailable or preflight.requires_approval:
            blocked_message = f"Approval resume blocked for tool '{existing_tool_name}'. Reason: {preflight.reason}"
            try:
                processed = process_approval_decision(request_id, "REJECTED")
            except Exception:
                processed = existing_request or {"tool_name": existing_tool_name, "session_id": "default_session"}
            _log_removed_tool_block(processed.get("session_id", "default_session"), existing_tool_name, policy_args, blocked_message)
            log_loop_event(
                session_id=processed.get("session_id", "default_session"),
                step_index=99,
                step_type="HITL_BLOCKED",
                reasoning=f"Approval resume blocked by policy for '{existing_tool_name}'",
                tool_name=existing_tool_name,
                tool_args=policy_args,
                tool_result=blocked_message,
            )
            return {
                "request_id": request_id,
                "status": "UNAVAILABLE" if preflight.unavailable else "BLOCKED",
                "tool_name": existing_tool_name,
                "tool_result": blocked_message,
                "response": blocked_message,
                "message": blocked_message,
            }

    processed = process_approval_decision(request_id, decision)
    tool_name = processed.get("tool_name", "")
    session_id = processed.get("session_id", "default_session")

    raw_args = processed.get("tool_args_json", "{}")
    try:
        tool_args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
    except Exception:
        tool_args = {}

    batch_calls = _parse_approved_tool_batch(tool_name, tool_args)
    tool_args = batch_calls[0]["args"] if batch_calls else {}

    # Load existing turns to preserve full conversation context
    past_turns = get_raw_turns(session_id=session_id)
    history_messages = []
    for turn in past_turns:
        sender = turn.get("sender")
        content = turn.get("content", "")
        if sender == "user":
            history_messages.append(HumanMessage(content=content))
        elif sender == "assistant":
            history_messages.append(AIMessage(content=content))

    _, tool_map = get_registered_tools()

    if decision.upper() == "APPROVED":
        outputs = []
        tool_messages = []
        ai_calls = []
        for item in batch_calls:
            item_name = item["name"]
            item_args = bind_email_send_args(
                item["args"],
                last_user_text=next((str(turn.get("content") or "") for turn in reversed(past_turns) if turn.get("sender") == "user"), ""),
                session_id=session_id,
            )
            item_id = item["id"]
            invocation = invoke_registered_tool(
                item_name,
                item_args,
                tool_map,
                source=ToolCallerSource.APPROVAL_RESUME,
                approval_context={"approved": True, "request_id": request_id},
            )
            item_output = invocation.to_text()
            outputs.append(item_output)
            log_loop_event(
                session_id=session_id,
                step_index=99,
                step_type="HITL_APPROVED",
                reasoning=f"Human operator APPROVED execution of '{item_name}'",
                tool_name=item_name,
                tool_args=item_args,
                tool_result=item_output,
            )
            tool_messages.append(ToolMessage(content=item_output, tool_call_id=item_id, name=item_name))
            ai_calls.append({"name": item_name, "args": item_args, "id": item_id})

        if len(outputs) == 1:
            tool_output = outputs[0]
        else:
            tool_output = "\n".join(
                f"[{index}/{len(outputs)}] {text}" for index, text in enumerate(outputs, start=1)
            )
        resume_messages = history_messages + [
            AIMessage(content="", tool_calls=ai_calls),
            *tool_messages,
        ]

        resume_state = {
            "messages": resume_messages,
            "session_id": session_id,
            "approval_status": "APPROVED",
            "tools_used": [tool_name],
            "loop_count": 1
        }
        res = agent_app.invoke(resume_state)
        messages = res.get("messages", [])
        final_response = _resume_user_response(messages, tool_output)

        return {
            "request_id": request_id,
            "status": "APPROVED",
            "tool_name": tool_name,
            "tool_result": tool_output,
            "response": final_response,
            "message": f"Approval GRANTED for tool '{tool_name}'. Result: {tool_output}"
        }

    else:
        log_loop_event(
            session_id=session_id,
            step_index=99,
            step_type="HITL_REJECTED",
            reasoning=f"Human operator REJECTED execution of '{tool_name}'",
            tool_name=tool_name,
            tool_args=tool_args,
            tool_result="Action REJECTED by human operator."
        )

        rejection_msgs = [
            ToolMessage(content="Action REJECTED by human operator.", tool_call_id=item["id"], name=item["name"])
            for item in batch_calls
        ]
        resume_state = {
            "messages": history_messages + [
                AIMessage(content="", tool_calls=[{"name": item["name"], "args": item["args"], "id": item["id"]} for item in batch_calls]),
                *rejection_msgs,
            ],
            "session_id": session_id,
            "approval_status": "REJECTED",
            "loop_count": 1
        }
        res = agent_app.invoke(resume_state)
        messages = res.get("messages", [])
        final_response = next((message_text(m) for m in reversed(messages) if isinstance(m, AIMessage) and message_text(m)), "Execution rejected.")

        return {
            "request_id": request_id,
            "status": "REJECTED",
            "tool_name": tool_name,
            "tool_result": "Action REJECTED by human operator.",
            "response": final_response,
            "message": f"Approval DENIED / REJECTED for tool '{tool_name}'."
        }




def build_agent_graph():
    """Compiles and returns the LangGraph workflow with an iterative agent loop."""
    workflow = StateGraph(AgentState)

    # Add Nodes
    workflow.add_node("ingest", node_ingest)
    workflow.add_node("manage_memory", node_manage_memory)
    workflow.add_node("memory_router", node_memory_router)
    workflow.add_node("agent", node_agent)
    workflow.add_node("hitl_check", node_hitl_check)
    workflow.add_node("tools", node_tools)
    workflow.add_node("consolidate", node_consolidate)

    # Add Edges
    workflow.add_edge(START, "ingest")
    workflow.add_edge("ingest", "manage_memory")
    workflow.add_edge("manage_memory", "memory_router")
    workflow.add_edge("memory_router", "agent")

    workflow.add_conditional_edges(
        "agent",
        should_continue,
        {
            "hitl_check": "hitl_check",
            "consolidate": "consolidate",
            "end": END
        }
    )

    workflow.add_conditional_edges(
        "hitl_check",
        route_after_hitl,
        {
            "tools": "tools",
            "end": END,
        },
    )
    workflow.add_edge("tools", "agent")
    workflow.add_edge("consolidate", END)

    return workflow.compile()

# Global compiled graph instance
agent_app = build_agent_graph()




