import uuid
from pathlib import Path
from typing import Dict, Any, Optional
from langchain_core.messages import SystemMessage, HumanMessage

from src.orchestration.registry import register_sub_agent, update_sub_agent_status

def execute_sub_agent(

    role: str,
    instructions: str,
    parent_session_id: str = "main_session",
    db_path: Optional[Path] = None
) -> Dict[str, Any]:
    """
    Executes an isolated sub-agent workflow.
    Context isolation is enforced by providing a specialized SystemMessage
    and separate session ID.
    """
    agent_id = f"sub_agent_{uuid.uuid4().hex[:8]}"

    # Register sub-agent in registry
    register_sub_agent(
        agent_id=agent_id,
        parent_session_id=parent_session_id,
        role=role,
        instructions=instructions,
        db_path=db_path
    )

    # Construct isolated state thread for sub-agent
    sub_system_prompt = SystemMessage(
        content=f"You are a specialized sub-agent.\nRole: {role}\nInstructions: {instructions}\nExecute your task concisely."
    )
    sub_user_task = HumanMessage(content=f"Task: Execute sub-agent duties for role '{role}'. Instructions: {instructions}")

    sub_state = {
        "messages": [sub_system_prompt, sub_user_task],
        "session_id": agent_id,
        "summary": "",
        "token_count": 0,
        "retrieval_triggered": False,
        "retrieved_memories": []
    }

    try:
        from src.harness.graph import agent_app
        result_state = agent_app.invoke(sub_state)

        latest_response = result_state["messages"][-1].content

        update_sub_agent_status(
            agent_id=agent_id,
            status="COMPLETED",
            result=latest_response,
            db_path=db_path
        )

        return {
            "agent_id": agent_id,
            "status": "COMPLETED",
            "role": role,
            "result": latest_response
        }
    except Exception as e:
        error_msg = f"Sub-agent execution failed: {str(e)}"
        update_sub_agent_status(
            agent_id=agent_id,
            status="FAILED",
            result=error_msg,
            db_path=db_path
        )
        return {
            "agent_id": agent_id,
            "status": "FAILED",
            "role": role,
            "result": error_msg
        }
