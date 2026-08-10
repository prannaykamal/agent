import os
import json
import uuid
from typing import List, Dict, Any, Optional
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import BaseMessage, SystemMessage, AIMessage, HumanMessage, ToolMessage

try:
    from langchain_openai import ChatOpenAI
except ImportError:
    ChatOpenAI = None

from src.config import PRIMARY_MODEL
from src.db import get_connection
from src.harness.state import AgentState
from src.memory.soul_loader import load_soul_prompt
from src.memory.short_term import estimate_tokens, log_raw_turn, get_raw_turns
from src.memory.summary_blocks import prepare_short_term_context_for_chat

from src.memory.retrieval_gate import should_retrieve_memory
from src.memory.context_assembler import ContextAssemblyOptions, assemble_retrieved_memory_context
from src.memory.retrieval_planner import build_retrieval_plan
from src.memory.retrieval_sources import retrieve_all_sources
from src.memory.semantic import search_facts_top_k, extract_and_save_facts
from src.memory.episodic import search_episodes_fts, log_episode
from src.memory.procedural import match_procedural_skills

from src.hitl.classifier import classify_tool_risk
from src.hitl.approval_engine import create_approval_request, process_approval_decision, get_approval_request
from src.tools.removed_tools import get_removed_tool_blocked_message, is_removed_tool_name
from src.tools.invocation import invoke_registered_tool
from src.tools.policy import ToolCallerSource, evaluate_tool_policy
from src.personal_os.checkpointing import checkpoint, restore_checkpoint
from src.harness.models import get_primary_llm
from src.harness.llm_router import resolve_primary_llm
from src.memory.jobs import enqueue_post_turn_memory_jobs

_ORIGINAL_GET_PRIMARY_LLM = get_primary_llm

def get_registered_tools():
    """Lazily fetches and maps all Personal OS native tools + MCP Gateway tools to avoid circular imports."""
    from src.personal_os.registry import get_all_personal_os_tools
    from src.mcp_gateway.registry import get_all_mcp_tools

    tools = get_all_personal_os_tools() + get_all_mcp_tools()
    tool_map = {t.name: t for t in tools}
    return tools, tool_map


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
    return {
        "id": event_id,
        "step_index": step_index,
        "step_type": step_type,
        "reasoning": reasoning,
        "tool_name": tool_name,
        "tool_args": tool_args,
        "tool_result": tool_result
    }


def node_ingest(state: AgentState) -> dict:
    """Node: Ensures SOUL system prompt is present in message history and logs raw user turn."""
    messages = list(state.get("messages", []))
    session_id = state.get("session_id", "default_session")
    events = list(state.get("loop_events") or [])
    soul_prompt = load_soul_prompt()

    has_system_prompt = any(isinstance(m, SystemMessage) for m in messages)
    if not has_system_prompt:
        messages = [soul_prompt] + messages

    # Log latest raw user turn uncompacted to SQLite raw_turns table
    last_user_msg = next((m.content for m in reversed(messages) if isinstance(m, HumanMessage)), None)
    if last_user_msg:
        log_raw_turn(session_id=session_id, sender="user", content=str(last_user_msg))
        evt = log_loop_event(
            session_id=session_id,
            step_index=0,
            step_type="USER_INPUT",
            reasoning=f"Ingested user message: '{last_user_msg}'"
        )
        events.append(evt)

    return {
        "messages": messages,
        "token_count": estimate_tokens(messages),
        "loop_count": 0,
        "tools_used": [],
        "loop_events": events
    }

def node_manage_memory(state: AgentState) -> dict:
    """Node: Reconstructs short-term context from immutable summary blocks and raw turns."""
    messages = list(state.get("messages", []))
    session_id = state.get("session_id", "default_session")

    context = prepare_short_term_context_for_chat(
        session_id=session_id,
        current_messages=messages,
        provider=state.get("provider", "openai"),
        model_name=state.get("model_name", "gpt-4o-mini"),
        secondary_provider=state.get("secondary_provider"),
        secondary_model_name=state.get("secondary_model_name"),
    )

    return {
        "messages": context.messages,
        "summary": "",
        "token_count": estimate_tokens(context.messages),
        "trimming_occurred": bool(context.omitted_unsummarized_turn_ids),
        "summary_status": context.status,
        "pending_summary_job_id": context.pending_summary_job_id,
    }

def _legacy_retrieval_gate_fallback(messages: List[BaseMessage], query: str) -> dict:
    """Best-effort legacy retrieval path used only if Phase 9B retrieval fails globally."""
    try:
        facts = search_facts_top_k(query=query, k=3)
        episodes = search_episodes_fts(query=query, limit=2)
        skills = match_procedural_skills(query=query)

        retrieved_items: List[Dict[str, Any]] = []
        memory_blocks = []
        if facts:
            fact_str = "\n".join(f"- [{f['category']}] {f['fact_text']}" for f in facts)
            memory_blocks.append(f"Semantic Facts:\n{fact_str}")
            retrieved_items.extend(facts)

        if episodes:
            ep_str = "\n".join(f"- {e['timestamp']}: {e['content']}" for e in episodes)
            memory_blocks.append(f"Past Episodes:\n{ep_str}")
            retrieved_items.extend(episodes)

        if skills:
            skill_str = "\n".join(f"- Skill '{s['name']}': {s['execution_steps']}" for s in skills)
            memory_blocks.append(f"Procedural Skills:\n{skill_str}")
            retrieved_items.extend(skills)

        if memory_blocks:
            context_block = "[Retrieved Long-Term Memory]\n" + "\n\n".join(memory_blocks)
            messages.append(SystemMessage(content=context_block))

        return {
            "messages": messages,
            "retrieval_triggered": bool(memory_blocks),
            "retrieved_memories": retrieved_items,
        }
    except Exception:
        return {
            "messages": messages,
            "retrieval_triggered": False,
            "retrieved_memories": [],
        }


def node_retrieval_gate(state: AgentState) -> dict:
    """Node: Runs Retrieval Gate and injects long-term memory if triggered."""
    messages = list(state.get("messages", []))
    last_user_msg = next((m.content for m in reversed(messages) if isinstance(m, HumanMessage)), "")

    needs_retrieval = should_retrieve_memory(str(last_user_msg))
    if not needs_retrieval or not last_user_msg:
        return {
            "messages": messages,
            "retrieval_triggered": False,
            "retrieved_memories": [],
        }

    query_str = str(last_user_msg)
    try:
        plan = build_retrieval_plan(
            query=query_str,
            session_id=state.get("session_id", "default_session"),
            provider=state.get("provider", "openai"),
            model_name=state.get("model_name", "gpt-4o-mini"),
            messages=messages,
            gate_allows_retrieval=needs_retrieval,
        )
        if not plan.should_retrieve or plan.retrieval_request is None:
            return {
                "messages": messages,
                "retrieval_triggered": False,
                "retrieved_memories": [],
            }

        bundle = retrieve_all_sources(plan.retrieval_request)
        assembled = assemble_retrieved_memory_context(
            bundle,
            ContextAssemblyOptions(
                total_token_budget=plan.total_token_budget,
                budget_by_kind=plan.budget_by_kind,
            ),
        )
        if assembled.block_text:
            messages.append(SystemMessage(content=assembled.block_text))

        return {
            "messages": messages,
            "retrieval_triggered": bool(assembled.block_text),
            "retrieved_memories": assembled.legacy_retrieved_items,
        }
    except Exception:
        return _legacy_retrieval_gate_fallback(messages, query_str)

def node_agent(state: AgentState) -> dict:
    """Node: Invokes Primary LLM bound with tools and advances loop step."""
    if state.get("approval_status") == "PENDING":
        return {}

    messages = list(state.get("messages", []))
    session_id = state.get("session_id", "default_session")
    provider = state.get("provider", "openai")
    model_name = state.get("model_name", "gpt-4o-mini")
    loop_count = (state.get("loop_count") or 0) + 1
    events = list(state.get("loop_events") or [])
    tools_used = list(state.get("tools_used") or [])

    tools, _ = get_registered_tools()
    primary_route = resolve_primary_llm(provider=provider, model_name=model_name)
    llm = primary_route.llm
    provider = primary_route.selector.provider
    model_name = primary_route.selector.model_name

    if llm is None and get_primary_llm is not _ORIGINAL_GET_PRIMARY_LLM:
        llm, _ = get_primary_llm(provider=provider, model_name=model_name)

    if llm and hasattr(llm, "bind_tools"):
        llm_with_tools = llm.bind_tools(tools)
        response = llm_with_tools.invoke(messages)
    else:
        last_user_msg = next((m.content for m in reversed(messages) if isinstance(m, HumanMessage)), "Hello")
        response_text = f"[{provider.capitalize()}/{model_name} Primary LLM (Offline)]: Processed request -> '{last_user_msg}'"
        response = AIMessage(content=response_text)

    tool_calls = getattr(response, "tool_calls", []) or []

    if tool_calls:
        evt_reasoning = log_loop_event(
            session_id=session_id,
            step_index=loop_count,
            step_type="REASONING",
            reasoning=str(response.content) if response.content else f"Decided to invoke tool(s): {', '.join([tc['name'] for tc in tool_calls])}"
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
            reasoning=str(response.content) if response.content else "[Final Response Generated]"
        )
        events.append(evt_final)

    # Log raw assistant response turn uncompacted
    if response and response.content:
        log_raw_turn(session_id=session_id, sender="assistant", content=str(response.content))

    return {
        "messages": [response],
        "loop_count": loop_count,
        "loop_events": events,
        "tools_used": tools_used
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

    detected_tool = None
    tool_args = {}
    tool_call_id = f"call_{uuid.uuid4().hex[:6]}"

    if tool_calls:
        detected_tool = tool_calls[0]["name"]
        tool_args = dict(tool_calls[0].get("args", {}))
        tool_call_id = tool_calls[0].get("id", tool_call_id)
    else:
        # Keyword detection fallback
        if "bank_transfer" in last_user_text or "transfer money" in last_user_text:
            detected_tool = "bank_transfer"
        elif "delete_database" in last_user_text or "drop database" in last_user_text:
            detected_tool = "delete_database"
        elif "production_deploy" in last_user_text or "deploy to production" in last_user_text:
            detected_tool = "production_deploy"
        elif "delete_files" in last_user_text or "delete file" in last_user_text:
            detected_tool = "delete_files"

    if detected_tool:
        risk_level, reason = classify_tool_risk(detected_tool)
        if risk_level == "High":
            chk_res = checkpoint.invoke({"task_id": session_id})
            checkpoint_id = chk_res.split("ID '")[1].split("' for task")[0] if "ID '" in chk_res else ""

            saved_args = dict(tool_args or {"input": last_user_text})
            saved_args["_tool_call_id"] = tool_call_id

            app_req = create_approval_request(
                session_id=session_id,
                tool_name=detected_tool,
                tool_args=saved_args,
                reason=reason,
                checkpoint_id=checkpoint_id
            )

            evt_hitl = log_loop_event(
                session_id=session_id,
                step_index=98,
                step_type="HITL_REQUIRED",
                tool_name=detected_tool,
                tool_args=tool_args,
                reasoning=f"High risk action '{detected_tool}' requires human approval. Reason: {reason}"
            )
            events.append(evt_hitl)

            pause_msg = AIMessage(
                content=(
                    f"[HUMAN APPROVAL REQUIRED - HIGH RISK TASK]\n"
                    f"Tool Requested: {detected_tool}\n"
                    f"Risk Justification: {reason}\n"
                    f"Approval Request ID: {app_req['request_id']}\n"
                    f"Execution paused. Please approve or reject this request to proceed."
                )
            )

            return {
                "messages": [pause_msg],
                "pending_approval_id": app_req['request_id'],
                "approval_status": "PENDING",
                "loop_events": events
            }

    return {"pending_approval_id": None, "approval_status": "NONE"}

def node_tools(state: AgentState) -> dict:
    """Node: Executes requested tool calls, records observations, and updates loop events."""
    messages = list(state.get("messages", []))
    session_id = state.get("session_id", "default_session")
    loop_count = state.get("loop_count", 1)
    events = list(state.get("loop_events") or [])
    tools_used = list(state.get("tools_used") or [])
    approval_status = state.get("approval_status")

    _, tool_map = get_registered_tools()
    last_ai = messages[-1]
    tool_calls = getattr(last_ai, "tool_calls", [])

    tool_messages = []
    for call in tool_calls:
        tname = call["name"]
        targs = call.get("args", {})
        tcall_id = call.get("id", f"call_{uuid.uuid4().hex[:6]}")

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

    return {
        "messages": tool_messages,
        "tools_used": tools_used,
        "loop_events": events
    }

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
    last_user_text = next((str(m.content) for m in reversed(messages) if isinstance(m, HumanMessage)), "").lower()

    if loop_count >= 10:
        return "consolidate"

    is_high_risk_keyword = any(kw in last_user_text for kw in ["bank_transfer", "delete_database", "production_deploy", "delete_files", "email_send"])

    if tool_calls or is_high_risk_keyword:
        return "hitl_check"

    return "consolidate"


def resume_graph_after_approval(request_id: str, decision: str) -> Dict[str, Any]:
    """Resumes or aborts graph execution after human approval decision ('APPROVED' or 'REJECTED'). Preserves full conversation state."""
    existing_request = get_approval_request(request_id)
    existing_tool_name = str((existing_request or {}).get("tool_name") or "")
    if str(decision or "").upper().strip() == "APPROVED" and is_removed_tool_name(existing_tool_name):
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
        if isinstance(existing_tool_args, dict):
            policy_args = {key: value for key, value in existing_tool_args.items() if key != "_tool_call_id"}
        else:
            policy_args = {}
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
    checkpoint_id = processed.get("checkpoint_id", "")
    tool_name = processed.get("tool_name", "")
    session_id = processed.get("session_id", "default_session")

    raw_args = processed.get("tool_args_json", "{}")
    try:
        tool_args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
    except Exception:
        tool_args = {}

    tool_call_id = tool_args.pop("_tool_call_id", f"call_{uuid.uuid4().hex[:6]}") if isinstance(tool_args, dict) else f"call_{uuid.uuid4().hex[:6]}"

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
        policy_args = tool_args if isinstance(tool_args, dict) else {}
        invocation = invoke_registered_tool(
            tool_name,
            policy_args,
            tool_map,
            source=ToolCallerSource.APPROVAL_RESUME,
            approval_context={"approved": True, "request_id": request_id},
        )
        if invocation.ok:
            tool_output = invocation.to_text()
        elif invocation.policy_decision and invocation.policy_decision.metadata.get("legacy_hitl_demo_tool"):
            tool_output = f"Tool '{tool_name}' executed successfully upon human approval."
        else:
            tool_output = invocation.to_text()
        log_loop_event(
            session_id=session_id,
            step_index=99,
            step_type="HITL_APPROVED",
            reasoning=f"Human operator APPROVED execution of '{tool_name}'",
            tool_name=tool_name,
            tool_args=tool_args,
            tool_result=tool_output
        )

        tool_msg = ToolMessage(content=tool_output, tool_call_id=tool_call_id, name=tool_name)
        resume_messages = history_messages + [tool_msg]

        resume_state = {
            "messages": resume_messages,
            "session_id": session_id,
            "approval_status": "APPROVED",
            "tools_used": [tool_name],
            "loop_count": 1
        }
        res = agent_app.invoke(resume_state)
        messages = res.get("messages", [])
        final_response = next((str(m.content) for m in reversed(messages) if isinstance(m, AIMessage) and m.content), tool_output)

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

        rejection_msg = ToolMessage(content="Action REJECTED by human operator.", tool_call_id=tool_call_id, name=tool_name)
        resume_state = {
            "messages": [rejection_msg],
            "session_id": session_id,
            "approval_status": "REJECTED",
            "loop_count": 1
        }
        res = agent_app.invoke(resume_state)
        messages = res.get("messages", [])
        final_response = next((str(m.content) for m in reversed(messages) if isinstance(m, AIMessage) and m.content), "Execution rejected.")

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
    workflow.add_node("retrieval_gate", node_retrieval_gate)
    workflow.add_node("agent", node_agent)
    workflow.add_node("hitl_check", node_hitl_check)
    workflow.add_node("tools", node_tools)
    workflow.add_node("consolidate", node_consolidate)

    # Add Edges
    workflow.add_edge(START, "ingest")
    workflow.add_edge("ingest", "manage_memory")
    workflow.add_edge("manage_memory", "retrieval_gate")
    workflow.add_edge("retrieval_gate", "agent")

    workflow.add_conditional_edges(
        "agent",
        should_continue,
        {
            "hitl_check": "hitl_check",
            "consolidate": "consolidate",
            "end": END
        }
    )

    workflow.add_edge("hitl_check", "tools")
    workflow.add_edge("tools", "agent")
    workflow.add_edge("consolidate", END)

    return workflow.compile()

# Global compiled graph instance
agent_app = build_agent_graph()

