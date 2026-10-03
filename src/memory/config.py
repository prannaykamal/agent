import os
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional


SUPPORTED_CONFIG_SOURCES = ("environment", "defaults")


@dataclass(frozen=True)
class LLMRoleConfig:
    provider: str
    model_name: str
    temperature: float
    context_window: int


@dataclass(frozen=True)
class ShortTermMemoryConfig:
    conversation_budget_ratio: float = 0.75
    summarization_trigger_ratio: float = 0.90
    output_reserve_ratio: float = 0.10
    safety_margin_ratio: float = 0.05
    max_summary_blocks: int = 20


@dataclass(frozen=True)
class AdaptiveSummarizationConfig:
    small_context_chunk_ratio: float = 0.30
    medium_context_chunk_ratio: float = 0.25
    large_context_chunk_ratio: float = 0.20
    small_context_max_tokens: int = 200000
    medium_context_max_tokens: int = 500000


COGNEE_SEARCH_TYPES = (
    "GRAPH_COMPLETION",
    "RAG_COMPLETION",
    "CHUNKS",
    "SUMMARIES",
)


@dataclass(frozen=True)
class CogneeMemoryConfig:
    """Long-term memory backed by a single cognee knowledge graph.

    Worth-storing turns go to a per-session cognee session cache first and are
    merged into the main graph (``dataset_name``) once the session is idle.
    Retrieval only ever reads the main graph.
    """

    enabled: bool = True
    storage_enabled: bool = True
    retrieval_enabled: bool = True
    dataset_name: str = "ivo_memory"
    data_dir: str = ""
    user_id: str = "default_user"
    search_type: str = "GRAPH_COMPLETION"
    top_k: int = 8
    recall_timeout_seconds: float = 8.0
    retrieval_token_budget: int = 1500
    session_idle_timeout_minutes: int = 30


@dataclass(frozen=True)
class JevConfig:
    """Jev: a small decision/routing model behind an OpenAI-compatible endpoint.

    The API key is read from ``JEV_API_KEY`` at call time and is deliberately
    not part of this config, because the config is exposed by ``/api/models``.
    """

    endpoint: str = ""
    model: str = ""
    timeout_seconds: float = 5.0
    tool_review_enabled: bool = True

    @property
    def configured(self) -> bool:
        return bool(self.endpoint and self.model)


@dataclass(frozen=True)
class QueueConfig:
    background_worker_count: int = 1
    maximum_queue_size: int = 1000
    retry_limit: int = 3
    retry_backoff_seconds: int = 30
    job_timeout_seconds: int = 300
    queue_persistence_enabled: bool = True
    idle_maintenance_interval_seconds: int = 86400


@dataclass(frozen=True)
class MetricsConfig:
    memory_metrics_enabled: bool = True
    queue_metrics_enabled: bool = True
    timing_metrics_enabled: bool = True
    cost_metrics_enabled: bool = False


@dataclass(frozen=True)
class MemoryArchitectureConfig:
    primary_llm: LLMRoleConfig
    secondary_llm: LLMRoleConfig
    short_term: ShortTermMemoryConfig
    adaptive_summarization: AdaptiveSummarizationConfig
    cognee: CogneeMemoryConfig
    jev: JevConfig
    queue: QueueConfig
    metrics: MetricsConfig
    config_sources: tuple[str, ...] = SUPPORTED_CONFIG_SOURCES

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _env_str(name: str, default: str) -> str:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a float") from exc


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


def _validate_ratio(name: str, value: float) -> None:
    if not 0 < value < 1:
        raise ValueError(f"{name} must be greater than 0 and less than 1")


def _validate_positive_int(name: str, value: int) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def _context_window_for(model_name: str, provider: str) -> int:
    from src.harness.models import get_context_window

    return get_context_window(model_name=model_name, provider=provider)


def _build_llm_role_config(
    role: str,
    provider_default: str,
    model_default: str,
    temperature_default: float,
) -> LLMRoleConfig:
    prefix = role.upper()
    provider = _env_str(f"{prefix}_PROVIDER", provider_default).lower()
    model_name = _env_str(f"{prefix}_MODEL", model_default)
    temperature = _env_float(f"{prefix}_TEMPERATURE", temperature_default)
    context_window = _context_window_for(model_name=model_name, provider=provider)
    _validate_ratio(f"{prefix}_TEMPERATURE_NORMALIZED", min(max(temperature, 0.0001), 0.9999))
    return LLMRoleConfig(
        provider=provider,
        model_name=model_name,
        temperature=temperature,
        context_window=context_window,
    )


def get_default_memory_config() -> MemoryArchitectureConfig:
    return load_memory_config(environ={})


def load_memory_config(environ: Optional[Dict[str, str]] = None) -> MemoryArchitectureConfig:
    """Load validated Phase X memory architecture configuration.

    The optional environ argument is a test seam. Runtime callers should omit it
    so values are read from the process environment.
    """
    previous = None
    if environ is not None:
        previous = os.environ.copy()
        os.environ.clear()
        os.environ.update(environ)

    try:
        primary = _build_llm_role_config(
            role="primary",
            provider_default="openai",
            model_default="GPT-5.5",
            temperature_default=0.7,
        )
        secondary = _build_llm_role_config(
            role="secondary",
            provider_default="openai",
            model_default="gpt-4o-mini",
            temperature_default=0.3,
        )

        short_term = ShortTermMemoryConfig(
            conversation_budget_ratio=_env_float("MEMORY_CONVERSATION_BUDGET_RATIO", 0.75),
            summarization_trigger_ratio=_env_float("MEMORY_SUMMARIZATION_TRIGGER_RATIO", 0.90),
            output_reserve_ratio=_env_float("MEMORY_OUTPUT_RESERVE_RATIO", 0.10),
            safety_margin_ratio=_env_float("MEMORY_SAFETY_MARGIN_RATIO", 0.05),
            max_summary_blocks=_env_int("MEMORY_MAX_SUMMARY_BLOCKS", 20),
        )

        adaptive = AdaptiveSummarizationConfig(
            small_context_chunk_ratio=_env_float("MEMORY_SMALL_CONTEXT_CHUNK_RATIO", 0.30),
            medium_context_chunk_ratio=_env_float("MEMORY_MEDIUM_CONTEXT_CHUNK_RATIO", 0.25),
            large_context_chunk_ratio=_env_float("MEMORY_LARGE_CONTEXT_CHUNK_RATIO", 0.20),
            small_context_max_tokens=_env_int("MEMORY_SMALL_CONTEXT_MAX_TOKENS", 200000),
            medium_context_max_tokens=_env_int("MEMORY_MEDIUM_CONTEXT_MAX_TOKENS", 500000),
        )

        cognee = CogneeMemoryConfig(
            enabled=_env_bool("COGNEE_ENABLED", True),
            storage_enabled=_env_bool("MEMORY_STORAGE_ENABLED", True),
            retrieval_enabled=_env_bool("MEMORY_RETRIEVAL_ENABLED", True),
            dataset_name=_env_str("MEMORY_COGNEE_DATASET", "ivo_memory"),
            data_dir=_env_str("MEMORY_COGNEE_DATA_DIR", ""),
            user_id=_env_str("MEMORY_USER_ID", "default_user"),
            search_type=_env_str("MEMORY_COGNEE_SEARCH_TYPE", "GRAPH_COMPLETION").upper(),
            top_k=_env_int("MEMORY_COGNEE_TOP_K", 8),
            recall_timeout_seconds=_env_float("MEMORY_COGNEE_RECALL_TIMEOUT_SECONDS", 8.0),
            retrieval_token_budget=_env_int("MEMORY_COGNEE_RETRIEVAL_TOKEN_BUDGET", 1500),
            session_idle_timeout_minutes=_env_int("SESSION_IDLE_TIMEOUT", 30),
        )

        jev = JevConfig(
            endpoint=_env_str("JEV_ENDPOINT", "").rstrip("/"),
            model=_env_str("JEV_MODEL", ""),
            timeout_seconds=_env_float("JEV_TIMEOUT_SECONDS", 5.0),
            tool_review_enabled=_env_bool("TOOL_JEV_ENABLED", True),
        )

        queue = QueueConfig(
            background_worker_count=_env_int("MEMORY_QUEUE_WORKER_COUNT", 1),
            maximum_queue_size=_env_int("MEMORY_QUEUE_MAX_SIZE", 1000),
            retry_limit=_env_int("MEMORY_QUEUE_RETRY_LIMIT", 3),
            retry_backoff_seconds=_env_int("MEMORY_QUEUE_RETRY_BACKOFF_SECONDS", 30),
            job_timeout_seconds=_env_int("MEMORY_QUEUE_JOB_TIMEOUT_SECONDS", 300),
            queue_persistence_enabled=_env_bool("MEMORY_QUEUE_PERSISTENCE_ENABLED", True),
            idle_maintenance_interval_seconds=_env_int("MEMORY_IDLE_MAINTENANCE_INTERVAL_SECONDS", 86400),
        )

        metrics = MetricsConfig(
            memory_metrics_enabled=_env_bool("MEMORY_METRICS_ENABLED", True),
            queue_metrics_enabled=_env_bool("MEMORY_QUEUE_METRICS_ENABLED", True),
            timing_metrics_enabled=_env_bool("MEMORY_TIMING_METRICS_ENABLED", True),
            cost_metrics_enabled=_env_bool("MEMORY_COST_METRICS_ENABLED", False),
        )

        _validate_config(
            short_term=short_term,
            adaptive=adaptive,
            cognee=cognee,
            jev=jev,
            queue=queue,
        )

        return MemoryArchitectureConfig(
            primary_llm=primary,
            secondary_llm=secondary,
            short_term=short_term,
            adaptive_summarization=adaptive,
            cognee=cognee,
            jev=jev,
            queue=queue,
            metrics=metrics,
        )
    finally:
        if previous is not None:
            os.environ.clear()
            os.environ.update(previous)


def _validate_config(
    short_term: ShortTermMemoryConfig,
    adaptive: AdaptiveSummarizationConfig,
    cognee: CogneeMemoryConfig,
    jev: JevConfig,
    queue: QueueConfig,
) -> None:
    for name, value in {
        "MEMORY_CONVERSATION_BUDGET_RATIO": short_term.conversation_budget_ratio,
        "MEMORY_SUMMARIZATION_TRIGGER_RATIO": short_term.summarization_trigger_ratio,
        "MEMORY_OUTPUT_RESERVE_RATIO": short_term.output_reserve_ratio,
        "MEMORY_SAFETY_MARGIN_RATIO": short_term.safety_margin_ratio,
        "MEMORY_SMALL_CONTEXT_CHUNK_RATIO": adaptive.small_context_chunk_ratio,
        "MEMORY_MEDIUM_CONTEXT_CHUNK_RATIO": adaptive.medium_context_chunk_ratio,
        "MEMORY_LARGE_CONTEXT_CHUNK_RATIO": adaptive.large_context_chunk_ratio,
    }.items():
        _validate_ratio(name, value)

    for name, value in {
        "MEMORY_MAX_SUMMARY_BLOCKS": short_term.max_summary_blocks,
        "MEMORY_SMALL_CONTEXT_MAX_TOKENS": adaptive.small_context_max_tokens,
        "MEMORY_MEDIUM_CONTEXT_MAX_TOKENS": adaptive.medium_context_max_tokens,
        "MEMORY_COGNEE_TOP_K": cognee.top_k,
        "MEMORY_COGNEE_RETRIEVAL_TOKEN_BUDGET": cognee.retrieval_token_budget,
        "SESSION_IDLE_TIMEOUT": cognee.session_idle_timeout_minutes,
        "MEMORY_QUEUE_WORKER_COUNT": queue.background_worker_count,
        "MEMORY_QUEUE_MAX_SIZE": queue.maximum_queue_size,
        "MEMORY_QUEUE_RETRY_LIMIT": queue.retry_limit,
        "MEMORY_QUEUE_RETRY_BACKOFF_SECONDS": queue.retry_backoff_seconds,
        "MEMORY_QUEUE_JOB_TIMEOUT_SECONDS": queue.job_timeout_seconds,
        "MEMORY_IDLE_MAINTENANCE_INTERVAL_SECONDS": queue.idle_maintenance_interval_seconds,
    }.items():
        _validate_positive_int(name, value)

    if cognee.search_type not in COGNEE_SEARCH_TYPES:
        raise ValueError(f"MEMORY_COGNEE_SEARCH_TYPE must be one of {', '.join(COGNEE_SEARCH_TYPES)}")
    if cognee.recall_timeout_seconds <= 0:
        raise ValueError("MEMORY_COGNEE_RECALL_TIMEOUT_SECONDS must be positive")
    if not cognee.dataset_name.replace("_", "").replace("-", "").isalnum():
        raise ValueError("MEMORY_COGNEE_DATASET may only contain letters, digits, '_' and '-'")
    if not cognee.user_id.replace("_", "").replace("-", "").isalnum():
        raise ValueError("MEMORY_USER_ID may only contain letters, digits, '_' and '-'")
    if jev.timeout_seconds <= 0:
        raise ValueError("JEV_TIMEOUT_SECONDS must be positive")
    if jev.endpoint and not jev.endpoint.startswith(("http://", "https://")):
        raise ValueError("JEV_ENDPOINT must be an http(s) URL")

    if adaptive.small_context_max_tokens > adaptive.medium_context_max_tokens:
        raise ValueError("MEMORY_SMALL_CONTEXT_MAX_TOKENS must be <= MEMORY_MEDIUM_CONTEXT_MAX_TOKENS")
