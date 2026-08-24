import pytest

from src.memory.config import load_memory_config


def test_phase1_memory_config_defaults_match_architecture():
    cfg = load_memory_config(environ={})

    assert cfg.primary_llm.provider == "openai"
    assert cfg.primary_llm.model_name == "GPT-5.5"
    assert cfg.secondary_llm.provider == "openai"
    assert cfg.secondary_llm.model_name == "gpt-4o-mini"

    assert cfg.short_term.conversation_budget_ratio == 0.75
    assert cfg.short_term.summarization_trigger_ratio == 0.90
    assert cfg.adaptive_summarization.small_context_chunk_ratio == 0.30
    assert cfg.adaptive_summarization.medium_context_chunk_ratio == 0.25
    assert cfg.adaptive_summarization.large_context_chunk_ratio == 0.20
    assert cfg.adaptive_summarization.small_context_max_tokens == 200000
    assert cfg.adaptive_summarization.medium_context_max_tokens == 500000

    assert cfg.semantic.consolidation_episode_frequency == 10
    assert cfg.semantic.consolidation_pending_fact_frequency == 100
    assert cfg.semantic.deduplication_top_k_min == 3
    assert cfg.semantic.deduplication_top_k_max == 10

    assert cfg.procedural.promotion_occurrence_threshold == 3
    assert cfg.procedural.promotion_confidence_threshold == 0.90
    assert cfg.procedural.consolidation_episode_frequency == 10
    assert cfg.procedural.consolidation_candidate_frequency == 20
    assert cfg.procedural.max_retrieved_procedural_skills == 3

    assert cfg.queue.queue_persistence_enabled is True
    assert cfg.metrics.memory_metrics_enabled is True


def test_phase1_memory_config_environment_overrides():
    cfg = load_memory_config(environ={
        "PRIMARY_PROVIDER": "anthropic",
        "PRIMARY_MODEL": "claude-3-5-sonnet-latest",
        "SECONDARY_PROVIDER": "gemini",
        "SECONDARY_MODEL": "gemini-1.5-flash",
        "MEMORY_CONVERSATION_BUDGET_RATIO": "0.70",
        "MEMORY_SUMMARIZATION_TRIGGER_RATIO": "0.85",
        "MEMORY_SEMANTIC_DEDUP_TOP_K_MIN": "4",
        "MEMORY_SEMANTIC_DEDUP_TOP_K_MAX": "8",
        "MEMORY_PROCEDURAL_PROMOTION_OCCURRENCES": "5",
        "MEMORY_PROCEDURAL_PROMOTION_CONFIDENCE": "0.95",
        "MEMORY_QUEUE_WORKER_COUNT": "2",
        "MEMORY_COST_METRICS_ENABLED": "true",
    })

    assert cfg.primary_llm.provider == "anthropic"
    assert cfg.primary_llm.model_name == "claude-3-5-sonnet-latest"
    assert cfg.secondary_llm.provider == "gemini"
    assert cfg.secondary_llm.model_name == "gemini-1.5-flash"
    assert cfg.primary_llm.context_window == 200000
    assert cfg.secondary_llm.context_window == 1000000
    assert cfg.short_term.conversation_budget_ratio == 0.70
    assert cfg.short_term.summarization_trigger_ratio == 0.85
    assert cfg.semantic.deduplication_top_k_min == 4
    assert cfg.semantic.deduplication_top_k_max == 8
    assert cfg.procedural.promotion_occurrence_threshold == 5
    assert cfg.procedural.promotion_confidence_threshold == 0.95
    assert cfg.queue.background_worker_count == 2
    assert cfg.metrics.cost_metrics_enabled is True


@pytest.mark.parametrize("name,value", [
    ("MEMORY_CONVERSATION_BUDGET_RATIO", "1.5"),
    ("MEMORY_SUMMARIZATION_TRIGGER_RATIO", "0"),
    ("MEMORY_PROCEDURAL_PROMOTION_CONFIDENCE", "-0.1"),
])
def test_phase1_memory_config_rejects_invalid_ratios(name, value):
    with pytest.raises(ValueError):
        load_memory_config(environ={name: value})


def test_phase1_memory_config_rejects_invalid_positive_ints():
    with pytest.raises(ValueError):
        load_memory_config(environ={"MEMORY_QUEUE_WORKER_COUNT": "0"})


def test_phase1_memory_config_rejects_invalid_dedup_range():
    with pytest.raises(ValueError):
        load_memory_config(environ={
            "MEMORY_SEMANTIC_DEDUP_TOP_K_MIN": "10",
            "MEMORY_SEMANTIC_DEDUP_TOP_K_MAX": "3",
        })


def test_phase1_memory_config_to_dict_is_api_ready():
    data = load_memory_config(environ={}).to_dict()

    assert data["short_term"]["conversation_budget_ratio"] == 0.75
    assert data["semantic"]["deduplication_top_k_min"] == 3
    assert data["procedural"]["promotion_confidence_threshold"] == 0.90
