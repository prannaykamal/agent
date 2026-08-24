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


@dataclass(frozen=True)
class EpisodicMemoryConfig:
    conversation_idle_timeout_seconds: int = 2700
    episode_idle_timeout_seconds: int = 2700
    long_conversation_token_threshold: int = 50000
    max_episodic_memories: int = 10000


@dataclass(frozen=True)
class SemanticMemoryConfig:
    max_pending_facts: int = 100
    consolidation_episode_frequency: int = 10
    consolidation_pending_fact_frequency: int = 100
    candidate_batch_size: int = 25
    deduplication_top_k_min: int = 3
    deduplication_top_k_max: int = 10


@dataclass(frozen=True)
class ProceduralMemoryConfig:
    promotion_occurrence_threshold: int = 3
    promotion_confidence_threshold: float = 0.90
    max_procedural_candidates: int = 500
    max_active_procedural_skills: int = 100
    max_retrieved_procedural_skills: int = 3
    consolidation_episode_frequency: int = 10
    consolidation_candidate_frequency: int = 20


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
    episodic: EpisodicMemoryConfig
    semantic: SemanticMemoryConfig
    procedural: ProceduralMemoryConfig
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

        episodic = EpisodicMemoryConfig(
            conversation_idle_timeout_seconds=_env_int("MEMORY_CONVERSATION_IDLE_TIMEOUT_SECONDS", 2700),
            episode_idle_timeout_seconds=_env_int("MEMORY_EPISODE_IDLE_TIMEOUT_SECONDS", 2700),
            long_conversation_token_threshold=_env_int("MEMORY_LONG_CONVERSATION_TOKEN_THRESHOLD", 50000),
            max_episodic_memories=_env_int("MEMORY_MAX_EPISODIC_MEMORIES", 10000),
        )

        semantic = SemanticMemoryConfig(
            max_pending_facts=_env_int("MEMORY_MAX_PENDING_FACTS", 100),
            consolidation_episode_frequency=_env_int("MEMORY_SEMANTIC_CONSOLIDATION_EPISODE_FREQUENCY", 10),
            consolidation_pending_fact_frequency=_env_int("MEMORY_SEMANTIC_CONSOLIDATION_PENDING_FACT_FREQUENCY", 100),
            candidate_batch_size=_env_int("MEMORY_SEMANTIC_CANDIDATE_BATCH_SIZE", 25),
            deduplication_top_k_min=_env_int("MEMORY_SEMANTIC_DEDUP_TOP_K_MIN", 3),
            deduplication_top_k_max=_env_int("MEMORY_SEMANTIC_DEDUP_TOP_K_MAX", 10),
        )

        procedural = ProceduralMemoryConfig(
            promotion_occurrence_threshold=_env_int("MEMORY_PROCEDURAL_PROMOTION_OCCURRENCES", 3),
            promotion_confidence_threshold=_env_float("MEMORY_PROCEDURAL_PROMOTION_CONFIDENCE", 0.90),
            max_procedural_candidates=_env_int("MEMORY_MAX_PROCEDURAL_CANDIDATES", 500),
            max_active_procedural_skills=_env_int("MEMORY_MAX_ACTIVE_PROCEDURAL_SKILLS", 100),
            max_retrieved_procedural_skills=_env_int("MEMORY_MAX_RETRIEVED_PROCEDURAL_SKILLS", 3),
            consolidation_episode_frequency=_env_int("MEMORY_PROCEDURAL_CONSOLIDATION_EPISODE_FREQUENCY", 10),
            consolidation_candidate_frequency=_env_int("MEMORY_PROCEDURAL_CONSOLIDATION_CANDIDATE_FREQUENCY", 20),
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
            episodic=episodic,
            semantic=semantic,
            procedural=procedural,
            queue=queue,
        )

        return MemoryArchitectureConfig(
            primary_llm=primary,
            secondary_llm=secondary,
            short_term=short_term,
            adaptive_summarization=adaptive,
            episodic=episodic,
            semantic=semantic,
            procedural=procedural,
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
    episodic: EpisodicMemoryConfig,
    semantic: SemanticMemoryConfig,
    procedural: ProceduralMemoryConfig,
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
        "MEMORY_PROCEDURAL_PROMOTION_CONFIDENCE": procedural.promotion_confidence_threshold,
    }.items():
        _validate_ratio(name, value)

    for name, value in {
        "MEMORY_MAX_SUMMARY_BLOCKS": short_term.max_summary_blocks,
        "MEMORY_SMALL_CONTEXT_MAX_TOKENS": adaptive.small_context_max_tokens,
        "MEMORY_MEDIUM_CONTEXT_MAX_TOKENS": adaptive.medium_context_max_tokens,
        "MEMORY_CONVERSATION_IDLE_TIMEOUT_SECONDS": episodic.conversation_idle_timeout_seconds,
        "MEMORY_EPISODE_IDLE_TIMEOUT_SECONDS": episodic.episode_idle_timeout_seconds,
        "MEMORY_LONG_CONVERSATION_TOKEN_THRESHOLD": episodic.long_conversation_token_threshold,
        "MEMORY_MAX_EPISODIC_MEMORIES": episodic.max_episodic_memories,
        "MEMORY_MAX_PENDING_FACTS": semantic.max_pending_facts,
        "MEMORY_SEMANTIC_CONSOLIDATION_EPISODE_FREQUENCY": semantic.consolidation_episode_frequency,
        "MEMORY_SEMANTIC_CONSOLIDATION_PENDING_FACT_FREQUENCY": semantic.consolidation_pending_fact_frequency,
        "MEMORY_SEMANTIC_CANDIDATE_BATCH_SIZE": semantic.candidate_batch_size,
        "MEMORY_SEMANTIC_DEDUP_TOP_K_MIN": semantic.deduplication_top_k_min,
        "MEMORY_SEMANTIC_DEDUP_TOP_K_MAX": semantic.deduplication_top_k_max,
        "MEMORY_PROCEDURAL_PROMOTION_OCCURRENCES": procedural.promotion_occurrence_threshold,
        "MEMORY_MAX_PROCEDURAL_CANDIDATES": procedural.max_procedural_candidates,
        "MEMORY_MAX_ACTIVE_PROCEDURAL_SKILLS": procedural.max_active_procedural_skills,
        "MEMORY_MAX_RETRIEVED_PROCEDURAL_SKILLS": procedural.max_retrieved_procedural_skills,
        "MEMORY_PROCEDURAL_CONSOLIDATION_EPISODE_FREQUENCY": procedural.consolidation_episode_frequency,
        "MEMORY_PROCEDURAL_CONSOLIDATION_CANDIDATE_FREQUENCY": procedural.consolidation_candidate_frequency,
        "MEMORY_QUEUE_WORKER_COUNT": queue.background_worker_count,
        "MEMORY_QUEUE_MAX_SIZE": queue.maximum_queue_size,
        "MEMORY_QUEUE_RETRY_LIMIT": queue.retry_limit,
        "MEMORY_QUEUE_RETRY_BACKOFF_SECONDS": queue.retry_backoff_seconds,
        "MEMORY_QUEUE_JOB_TIMEOUT_SECONDS": queue.job_timeout_seconds,
        "MEMORY_IDLE_MAINTENANCE_INTERVAL_SECONDS": queue.idle_maintenance_interval_seconds,
    }.items():
        _validate_positive_int(name, value)

    if semantic.deduplication_top_k_min > semantic.deduplication_top_k_max:
        raise ValueError("MEMORY_SEMANTIC_DEDUP_TOP_K_MIN must be <= MEMORY_SEMANTIC_DEDUP_TOP_K_MAX")

    if adaptive.small_context_max_tokens > adaptive.medium_context_max_tokens:
        raise ValueError("MEMORY_SMALL_CONTEXT_MAX_TOKENS must be <= MEMORY_MEDIUM_CONTEXT_MAX_TOKENS")
