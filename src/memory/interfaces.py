from typing import Any, Dict, List, Protocol, Sequence

from langchain_core.messages import BaseMessage

from src.memory.types import (
    MemoryJobType,
    RetrievalRequest,
    RetrievedMemory,
    SummaryBlock,
)


class TokenCounter(Protocol):
    def count_text(self, text: str, model_name: str) -> int:
        ...

    def count_messages(self, messages: Sequence[BaseMessage], model_name: str) -> int:
        ...


class ShortTermMemoryManager(Protocol):
    def prepare_context(self, request: RetrievalRequest) -> List[SummaryBlock]:
        ...


class EpisodicMemoryStore(Protocol):
    def retrieve(self, request: RetrievalRequest) -> List[RetrievedMemory]:
        ...


class SemanticMemoryStore(Protocol):
    def retrieve(self, request: RetrievalRequest) -> List[RetrievedMemory]:
        ...


class ProceduralMemoryStore(Protocol):
    def retrieve(self, request: RetrievalRequest) -> List[RetrievedMemory]:
        ...


class MemoryQueue(Protocol):
    def enqueue(
        self,
        job_type: MemoryJobType,
        payload: Dict[str, Any],
        idempotency_key: str,
    ) -> str:
        ...


class RetrievalPlanner(Protocol):
    def plan(self, request: RetrievalRequest) -> List[RetrievedMemory]:
        ...
