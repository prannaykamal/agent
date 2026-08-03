from typing import Optional, Dict, Any
from src.harness.models import get_secondary_llm
from src.memory.semantic import (
    add_semantic_fact,
    extract_and_save_facts,
    should_run_periodic_consolidation,
    run_periodic_consolidation
)
from src.memory.episodic import (
    log_episode,
    should_trigger_episode,
    generate_structured_episode_summary,
    create_structured_episode
)

def run_secondary_fact_extraction(
    user_input: str,
    assistant_output: str,
    provider: str = "openai",
    session_id: str = "default_session",
    task_completed: bool = False,
    workflow_finished: bool = False,
    trimming_occurred: bool = False,
    token_count: int = 0
) -> None:
    """
    Invokes Secondary LLM in background to extract semantic facts, detect episodes, write structured summaries, and run periodic consolidation.
    """
    secondary_llm = get_secondary_llm(provider=provider)

    if secondary_llm:
        prompt = (
            f"Analyze the following interaction and extract any user preferences or facts:\n"
            f"User: {user_input}\nAssistant: {assistant_output}\n\n"
            f"Output facts as bullet points or write 'NONE'."
        )
        try:
            resp = secondary_llm.invoke(prompt)
            fact_text = str(resp.content).strip()
            if fact_text and "NONE" not in fact_text:
                add_semantic_fact(category="user_preference", fact_text=fact_text, source="secondary_llm")
        except Exception:
            pass

    # Basic regex extraction fallback
    extract_and_save_facts(user_input=user_input, assistant_output=assistant_output)
    log_episode(session_id=session_id, content=f"User: {user_input} | AI: {assistant_output}")

    # Check Episode Detector rules
    if should_trigger_episode(
        session_id=session_id,
        task_completed=task_completed,
        workflow_finished=workflow_finished,
        trimming_occurred=trimming_occurred,
        conversation_tokens=token_count
    ):
        history_text = f"User: {user_input}\nAssistant: {assistant_output}"
        structured_data = generate_structured_episode_summary(
            session_id=session_id,
            history_text=history_text,
            provider=provider
        )
        create_structured_episode(session_id=session_id, structured_data=structured_data)

    # Check 10-episode Periodic Consolidation trigger
    if should_run_periodic_consolidation():
        run_periodic_consolidation(provider=provider)
