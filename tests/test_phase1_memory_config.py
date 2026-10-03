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

    assert cfg.cognee.enabled is True
    assert cfg.cognee.dataset_name == "ivo_memory"
    assert cfg.cognee.data_dir == ""
    assert cfg.cognee.search_type == "SUMMARIES"
    assert cfg.cognee.top_k == 8
    assert cfg.cognee.recall_timeout_seconds == 8.0
    assert cfg.cognee.retrieval_token_budget == 1500
    assert cfg.cognee.session_idle_timeout_minutes == 30
    assert cfg.cognee.storage_enabled is True
    assert cfg.cognee.retrieval_enabled is True
    assert cfg.cognee.user_id == "default_user"
    assert cfg.jev.endpoint == "" and cfg.jev.model == ""
    assert cfg.jev.configured is False
    assert cfg.jev.tool_review_enabled is True

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
        "COGNEE_ENABLED": "false",
        "MEMORY_STORAGE_ENABLED": "false",
        "MEMORY_RETRIEVAL_ENABLED": "false",
        "SESSION_IDLE_TIMEOUT": "45",
        "JEV_ENDPOINT": "http://localhost:8001/v1/",
        "JEV_MODEL": "jev-small",
        "TOOL_JEV_ENABLED": "false",
        "MEMORY_COGNEE_DATASET": "work-memory",
        "MEMORY_COGNEE_SEARCH_TYPE": "chunks",
        "MEMORY_COGNEE_TOP_K": "4",
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
    assert cfg.cognee.enabled is False
    assert cfg.cognee.storage_enabled is False
    assert cfg.cognee.retrieval_enabled is False
    assert cfg.cognee.session_idle_timeout_minutes == 45
    assert cfg.jev.endpoint == "http://localhost:8001/v1"
    assert cfg.jev.model == "jev-small"
    assert cfg.jev.configured is True
    assert cfg.jev.tool_review_enabled is False
    assert cfg.cognee.dataset_name == "work-memory"
    assert cfg.cognee.search_type == "CHUNKS"
    assert cfg.cognee.top_k == 4
    assert cfg.queue.background_worker_count == 2
    assert cfg.metrics.cost_metrics_enabled is True


@pytest.mark.parametrize("name,value", [
    ("MEMORY_CONVERSATION_BUDGET_RATIO", "1.5"),
    ("MEMORY_SUMMARIZATION_TRIGGER_RATIO", "0"),
    ("MEMORY_LARGE_CONTEXT_CHUNK_RATIO", "-0.1"),
])
def test_phase1_memory_config_rejects_invalid_ratios(name, value):
    with pytest.raises(ValueError):
        load_memory_config(environ={name: value})


def test_phase1_memory_config_rejects_invalid_positive_ints():
    with pytest.raises(ValueError):
        load_memory_config(environ={"MEMORY_QUEUE_WORKER_COUNT": "0"})


@pytest.mark.parametrize("name,value", [
    ("MEMORY_COGNEE_SEARCH_TYPE", "CYPHER"),
    ("MEMORY_COGNEE_TOP_K", "0"),
    ("MEMORY_COGNEE_RECALL_TIMEOUT_SECONDS", "0"),
    ("MEMORY_COGNEE_DATASET", "../escape"),
    ("MEMORY_USER_ID", "a b"),
    ("SESSION_IDLE_TIMEOUT", "0"),
    ("JEV_ENDPOINT", "ftp://jev"),
    ("JEV_TIMEOUT_SECONDS", "0"),
])
def test_cognee_config_rejects_invalid_values(name, value):
    with pytest.raises(ValueError):
        load_memory_config(environ={name: value})


def test_phase1_memory_config_to_dict_is_api_ready():
    data = load_memory_config(environ={}).to_dict()

    assert data["short_term"]["conversation_budget_ratio"] == 0.75
    assert data["cognee"]["dataset_name"] == "ivo_memory"
    # The Jev API key is read at call time and never part of the exposed config.
    assert "api_key" not in data["jev"]
    assert "semantic" not in data and "episodic" not in data and "procedural" not in data
