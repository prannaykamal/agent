"""Long-term memory backed by a single cognee knowledge graph.

This module is the only place that talks to cognee.

Storage (background worker only):
    ``remember_in_session()`` -> ``cognee.remember(..., session_id=...)`` writes
    a worth-storing turn into the cognee session cache for that conversation.
    ``merge_session()`` -> ``cognee.improve(session_ids=[...])`` bridges the
    session into the main graph once the conversation has been idle.
    ``remember_permanent()`` -> ``cognee.remember(...)`` without a session, for
    explicit writes (API facts and procedures, legacy backfill).

Retrieval (chat):
    ``recall()`` -> ``cognee.search`` over the main graph dataset with
    ``only_context=True``, so cognee returns context and the primary LLM
    writes the answer. Session caches are never searched.

Sessions are scoped by user (``MEMORY_USER_ID``) so they cannot collide, and a
non-default user gets its own main-graph dataset.

cognee is async and caches database engines per event loop, so every call runs
on one dedicated background loop thread. cognee is imported lazily: when it is
not installed or disabled, recall returns nothing and the agent keeps working.
"""

import asyncio
import hashlib
import inspect
import logging
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from src.memory.config import CogneeMemoryConfig, load_memory_config

logger = logging.getLogger(__name__)

RETRIEVED_MEMORY_HEADER = "[Retrieved Long-Term Memory]"
_DEFAULT_USER_ID = "default_user"

# OpenAI embedding dimensions; cognee defaults to 3072 and fails on mismatch.
_KNOWN_EMBEDDING_DIMENSIONS = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}


class CogneeUnavailableError(RuntimeError):
    """Raised when cognee is disabled, not installed, or failed to initialize."""


class CogneeMergeError(RuntimeError):
    """A session merge did not complete and should be retried."""


@dataclass(frozen=True)
class RecalledMemory:
    content: str
    source: str = "cognee"

    def to_dict(self) -> Dict[str, Any]:
        return {"kind": "long_term", "content": self.content, "source": self.source}


@dataclass(frozen=True)
class RecallResult:
    memories: List[RecalledMemory]
    search_type: str
    available: bool
    error: Optional[str] = None

    def without_known(self, active_context: str) -> "RecallResult":
        """Drop recalled snippets already present verbatim in the active conversation."""
        haystack = _normalize(active_context)
        kept = [item for item in self.memories if _normalize(item.content) not in haystack]
        return RecallResult(memories=kept, search_type=self.search_type, available=self.available, error=self.error)

    def to_context_block(self, token_budget: int) -> str:
        if not self.memories:
            return ""
        header = (
            RETRIEVED_MEMORY_HEADER
            + "\nStored knowledge about the user from past conversations (not the current conversation):"
        )
        lines: List[str] = []
        used = _estimate_tokens(header)
        for memory in self.memories:
            text = " ".join(memory.content.split())
            cost = _estimate_tokens(f"- {text}") + 1
            if used + cost > token_budget:
                remaining_chars = max(0, (token_budget - used) * 4 - 8)
                if remaining_chars < 80:
                    break
                text = text[:remaining_chars].rstrip() + "..."
                cost = token_budget - used
            lines.append(f"- {text}")
            used += cost
            if used >= token_budget:
                break
        if not lines:
            return ""
        return header + "\n" + "\n".join(lines)


@dataclass(frozen=True)
class MergeOutcome:
    # "completed": merged; "covered": a concurrent run will include these entries;
    # "skipped": cognee had nothing to do.
    status: str
    session_key: str


def _normalize(text: str) -> str:
    return " ".join(str(text or "").lower().split())


def _safe_part(value: str) -> str:
    raw = str(value or "")
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "_", raw)[:64]
    if cleaned == raw:
        return cleaned
    # Sanitising can merge distinct ids; a short hash keeps them apart.
    return f"{cleaned}-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:8]}"


def session_key(user_id: str, session_id: str) -> str:
    """The cognee session id for one user's conversation."""
    return f"{_safe_part(user_id)}__{_safe_part(session_id)}"


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _is_placeholder(value: Optional[str]) -> bool:
    return not value or not value.strip() or value.strip().startswith("your_")


def resolve_data_dir(config: CogneeMemoryConfig) -> Path:
    if config.data_dir:
        return Path(config.data_dir).expanduser().resolve()
    from src.config import AGENT_DIR

    return AGENT_DIR / "cognee"


def prepare_cognee_environment(
    config: CogneeMemoryConfig,
    environ: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """Fill cognee's env settings from this project's .env without overriding explicit values.

    Returns the keys that were set so callers and tests can see what changed.
    """
    env = os.environ if environ is None else environ
    applied: Dict[str, str] = {}

    def set_default(key: str, value: Optional[str]) -> None:
        if value and not env.get(key):
            env[key] = value
            applied[key] = value

    openai_key = env.get("OPENAI_API_KEY")
    if not _is_placeholder(openai_key):
        set_default("LLM_API_KEY", openai_key)
        if not env.get("EMBEDDING_PROVIDER") or env.get("EMBEDDING_PROVIDER") == "openai":
            set_default("EMBEDDING_API_KEY", openai_key)

    embedding_model = (env.get("EMBEDDING_MODEL") or "").strip()
    bare_model = embedding_model.split("/")[-1]
    if bare_model in _KNOWN_EMBEDDING_DIMENSIONS:
        set_default("EMBEDDING_DIMENSIONS", str(_KNOWN_EMBEDDING_DIMENSIONS[bare_model]))

    data_dir = resolve_data_dir(config)
    set_default("SYSTEM_ROOT_DIRECTORY", str(data_dir / "system"))
    set_default("DATA_ROOT_DIRECTORY", str(data_dir / "data"))
    # A personal assistant should not phone home with usage telemetry by default.
    set_default("TELEMETRY_DISABLED", "1")
    # Session -> main graph merges are driven by our idle timeout, not cognee's own debounce.
    set_default("IMPROVE_AUTO_ENABLED", "false")
    return applied


class _LoopThread:
    """One long-lived event loop so cognee's async engines stay bound to a single loop."""

    def __init__(self) -> None:
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def _ensure(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is not None and self._thread is not None and self._thread.is_alive():
                return self._loop
            loop = asyncio.new_event_loop()
            thread = threading.Thread(target=loop.run_forever, name="cognee-loop", daemon=True)
            thread.start()
            self._loop, self._thread = loop, thread
            return loop

    def run(self, coro: Any, timeout: Optional[float]) -> Any:
        future = asyncio.run_coroutine_threadsafe(coro, self._ensure())
        try:
            return future.result(timeout=timeout)
        except BaseException:
            future.cancel()
            raise


def _supported_kwargs(func: Any, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """Drop keyword arguments the installed cognee version does not accept."""
    try:
        params = inspect.signature(func).parameters
    except (TypeError, ValueError):
        return kwargs
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return kwargs
    return {key: value for key, value in kwargs.items() if key in params}


_TEXT_KEYS = ("text", "content", "context", "summary", "description", "name")


def _flatten_search_results(results: Any) -> List[str]:
    """Normalize cognee search output across versions into plain text snippets."""
    out: List[str] = []

    def visit(item: Any) -> None:
        if item is None:
            return
        if isinstance(item, str):
            if item.strip():
                out.append(item.strip())
            return
        if isinstance(item, dict):
            if "search_result" in item:
                visit(item["search_result"])
                return
            if "payload" in item and isinstance(item["payload"], dict):
                visit(item["payload"])
                return
            for key in _TEXT_KEYS:
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    out.append(value.strip())
                    return
            return
        if isinstance(item, (list, tuple)):
            for child in item:
                visit(child)
            return
        payload = getattr(item, "payload", None)
        if isinstance(payload, dict):
            visit(payload)
            return
        for key in ("search_result",) + _TEXT_KEYS:
            value = getattr(item, key, None)
            if value is not None:
                visit(value)
                return

    visit(results)
    deduped: List[str] = []
    seen = set()
    for text in out:
        if text not in seen:
            seen.add(text)
            deduped.append(text)
    return deduped


class CogneeMemory:
    """Thin, synchronous facade over cognee for the agent runtime."""

    def __init__(self, config: Optional[CogneeMemoryConfig] = None, cognee_module: Any = None):
        self.config = config if config is not None else load_memory_config().cognee
        self._cognee = cognee_module
        self._init_error: Optional[str] = None
        self._init_lock = threading.Lock()
        self._loop = _LoopThread()

    # -- lifecycle -------------------------------------------------------

    def _module(self) -> Any:
        if not self.config.enabled:
            raise CogneeUnavailableError("cognee memory is disabled (COGNEE_ENABLED=false)")
        if self._cognee is not None:
            return self._cognee
        with self._init_lock:
            if self._cognee is not None:
                return self._cognee
            if self._init_error:
                raise CogneeUnavailableError(self._init_error)
            prepare_cognee_environment(self.config)
            try:
                import cognee  # noqa: PLC0415 - optional heavy dependency
            except Exception as exc:
                self._init_error = f"cognee is not importable: {type(exc).__name__}: {exc}"
                raise CogneeUnavailableError(self._init_error) from exc
            data_dir = resolve_data_dir(self.config)
            try:
                cognee.config.system_root_directory(str(data_dir / "system"))
                cognee.config.data_root_directory(str(data_dir / "data"))
            except Exception:
                logger.debug("cognee.config directory setters unavailable; relying on env", exc_info=True)
            self._cognee = cognee
            return cognee

    def _unavailable_reason(self) -> Optional[str]:
        try:
            self._module()
            return None
        except CogneeUnavailableError as exc:
            return str(exc)

    def is_available(self) -> bool:
        return self._unavailable_reason() is None

    def dataset_for(self, user_id: Optional[str] = None) -> str:
        """Main-graph dataset for a user. The default user keeps the configured name."""
        user = user_id or self.config.user_id
        if user == _DEFAULT_USER_ID:
            return self.config.dataset_name
        return f"{self.config.dataset_name}_{_safe_part(user)}"

    def status(self) -> Dict[str, Any]:
        reason = self._unavailable_reason()
        available = reason is None
        return {
            "backend": "cognee",
            "enabled": self.config.enabled,
            "available": available,
            "error": reason,
            "storage_enabled": self.config.storage_enabled,
            "retrieval_enabled": self.config.retrieval_enabled,
            "dataset_name": self.dataset_for(),
            "user_id": self.config.user_id,
            "search_type": self.config.search_type,
            "session_idle_timeout_minutes": self.config.session_idle_timeout_minutes,
            "data_dir": str(resolve_data_dir(self.config)),
            "version": getattr(self._cognee, "__version__", None) if available else None,
        }

    def _search_type(self, name: Optional[str] = None) -> Any:
        cognee = self._module()
        search_type_enum = getattr(cognee, "SearchType", None)
        if search_type_enum is None:
            from cognee.api.v1.search import SearchType as search_type_enum  # noqa: PLC0415
        return getattr(search_type_enum, (name or self.config.search_type).upper())

    def _run(self, coro: Any, timeout: Optional[float]) -> Any:
        return self._loop.run(coro, timeout)

    def _remember_fn(self) -> Any:
        remember = getattr(self._module(), "remember", None)
        if remember is None:
            raise CogneeUnavailableError("installed cognee has no remember(); cognee>=1.6 is required")
        return remember

    # -- write path (worker only) ----------------------------------------

    def remember_in_session(self, text: str, *, user_id: str, session_id: str, timeout: Optional[float] = 300) -> str:
        """Add one worth-storing turn to the conversation's cognee session cache.

        cognee saves the entry first and then embeds it for session recall. That
        embedding step fails open but retries with backoff for a minute or two when
        the embedding provider is down, so the timeout is generous: cutting it short
        would retry a write that already landed and duplicate the entry.
        """
        content = (text or "").strip()
        key = session_key(user_id, session_id)
        if not content:
            return key
        remember = self._remember_fn()
        kwargs = _supported_kwargs(
            remember,
            {"dataset_name": self.dataset_for(user_id), "session_id": key, "self_improvement": False},
        )
        self._run(remember(content, **kwargs), timeout)
        return key

    def merge_session(self, *, user_id: str, session_id: str, timeout: Optional[float] = None) -> MergeOutcome:
        """Bridge a session cache into the main graph. Raises CogneeMergeError when it should be retried."""
        cognee = self._module()
        improve = getattr(cognee, "improve", None)
        if improve is None:
            raise CogneeUnavailableError("installed cognee has no improve(); cognee>=1.6 is required")
        key = session_key(user_id, session_id)
        kwargs = _supported_kwargs(improve, {"session_ids": [key]})
        result = self._run(improve(self.dataset_for(user_id), **kwargs), timeout)
        return MergeOutcome(status=_interpret_improve_result(result), session_key=key)

    def remember_permanent(self, texts: Sequence[str], *, user_id: Optional[str] = None, timeout: Optional[float] = None) -> None:
        """Write explicit knowledge straight into the main graph (add + cognify)."""
        items = [text.strip() for text in texts if text and text.strip()]
        if not items:
            return
        remember = self._remember_fn()
        kwargs = _supported_kwargs(remember, {"dataset_name": self.dataset_for(user_id), "self_improvement": False})
        self._run(remember(items if len(items) > 1 else items[0], **kwargs), timeout)

    # -- read path (chat) ------------------------------------------------

    def recall(
        self,
        query: str,
        *,
        user_id: Optional[str] = None,
        top_k: Optional[int] = None,
        search_type: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> RecallResult:
        """Return main-graph context relevant to ``query``. Never raises."""
        effective_type = (search_type or self.config.search_type).upper()
        if not (query or "").strip():
            return RecallResult(memories=[], search_type=effective_type, available=self.config.enabled)
        try:
            cognee = self._module()
        except CogneeUnavailableError as exc:
            return RecallResult(memories=[], search_type=effective_type, available=False, error=str(exc))

        kwargs: Dict[str, Any] = {
            "query_text": query,
            "query_type": self._search_type(effective_type),
            "datasets": [self.dataset_for(user_id)],
            "top_k": top_k or self.config.top_k,
            # Return retrieved context only; the primary chat model writes the answer.
            "only_context": effective_type in {"GRAPH_COMPLETION", "RAG_COMPLETION"},
        }
        kwargs = _supported_kwargs(cognee.search, kwargs)
        try:
            raw = self._run(
                cognee.search(**kwargs),
                timeout if timeout is not None else self.config.recall_timeout_seconds,
            )
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            # An empty main graph (nothing merged yet) is a normal cold start, not a failure.
            if type(exc).__name__ in {"NoDataError", "DatasetNotFoundError"} or "no data" in message.lower():
                return RecallResult(memories=[], search_type=effective_type, available=True)
            logger.warning("cognee recall failed: %s", type(exc).__name__)
            return RecallResult(memories=[], search_type=effective_type, available=True, error=message)

        snippets = _flatten_search_results(raw)[: top_k or self.config.top_k]
        return RecallResult(
            memories=[RecalledMemory(content=text) for text in snippets],
            search_type=effective_type,
            available=True,
        )

    # -- maintenance -----------------------------------------------------

    def forget_all(self, timeout: Optional[float] = 300) -> None:
        """Delete all cognee data and graph state for this deployment."""
        cognee = self._module()
        forget = getattr(cognee, "forget", None)
        if forget is not None:
            self._run(forget(everything=True), timeout)
            return
        self._run(cognee.prune.prune_data(), timeout)
        self._run(cognee.prune.prune_system(metadata=True), timeout)


def _interpret_improve_result(result: Any) -> str:
    """Map cognee's ImproveResult onto completed/covered/skipped, raising when a retry is needed."""
    if result is None:
        return "completed"
    status = getattr(result, "status", None)
    if status is None and isinstance(result, dict):
        status = result.get("status")
    error = getattr(result, "error", None) or (result.get("error") if isinstance(result, dict) else None)
    if status == "errored" or error:
        raise CogneeMergeError(f"improve errored: {str(error or 'stage error')[:200]}")
    if status == "running":
        raise CogneeMergeError("improve still running")
    if status == "skipped":
        stages = getattr(result, "stages", None) or []
        lock_held = any(getattr(stage, "reason", None) == "lock_held" for stage in stages)
        if lock_held:
            if getattr(result, "rerun_requested", False):
                return "covered"
            raise CogneeMergeError("improve lock held by another run")
        return "skipped"
    return "completed"


_DEFAULT: Optional[CogneeMemory] = None
_DEFAULT_LOCK = threading.Lock()


def get_cognee_memory() -> CogneeMemory:
    global _DEFAULT
    with _DEFAULT_LOCK:
        if _DEFAULT is None:
            _DEFAULT = CogneeMemory()
        return _DEFAULT


def set_cognee_memory(memory: Optional[CogneeMemory]) -> None:
    """Test seam: replace or reset the process-wide memory instance."""
    global _DEFAULT
    with _DEFAULT_LOCK:
        _DEFAULT = memory
