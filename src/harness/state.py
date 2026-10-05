from typing import TypedDict, Sequence, Annotated, List, Dict, Any, Optional
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

class AgentState(TypedDict):
    """LangGraph State representation for the agent harness with loop tracking, memory, HITL, and multi-model."""
    messages: Annotated[Sequence[BaseMessage], add_messages]
    session_id: str
    summary: str
    token_count: int
    retrieval_triggered: bool
    retrieved_memories: List[Dict[str, Any]]
    pending_approval_id: Optional[str]
    approval_status: Optional[str]
    provider: Optional[str]
    model_name: Optional[str]
    secondary_provider: Optional[str]
    secondary_model_name: Optional[str]
    memory_config_version: Optional[str]
    memory_job_ids: Optional[List[str]]
    summary_omitted_turn_ids: Optional[List[str]]
    # Long-term memory routing (cognee + Jev). Kept apart from tool execution state.
    user_id: Optional[str]
    memory_storage_decision: Optional[Dict[str, Any]]
    memory_retrieval_decision: Optional[Dict[str, Any]]
    # Set only on HITL resumes: the paused turn's original request, used for the
    # storage decision and the stored turn instead of a chat approval reply.
    memory_turn_user_text: Optional[str]
    loop_count: Optional[int]
    tools_used: Optional[List[str]]
    loop_events: Optional[List[Dict[str, Any]]]




