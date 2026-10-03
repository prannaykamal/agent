import pytest
from src.harness.models import get_primary_llm, get_secondary_llm, get_context_window, get_model_catalog, MODEL_PAIRS
from src.db import init_db

@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_tiered_db.db"
    mem_file = tmp_path / "MEMORY.md"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    monkeypatch.setattr("src.config.MEMORY_PATH", mem_file)
    init_db(db_file)
    return db_file

def test_tiered_model_pairs_catalog():
    catalog = get_model_catalog()
    assert "pairs" in catalog
    pairs = catalog["pairs"]

    assert pairs["openai"]["primary"] == "GPT-5.5"
    assert pairs["openai"]["secondary"] == "gpt-4o-mini"
    assert pairs["openai"]["context_window"] == 128000

    assert pairs["anthropic"]["context_window"] == 200000
    assert pairs["gemini"]["context_window"] == 1000000

def test_context_window_capacities():
    assert get_context_window("GPT-5.5") == 128000
    assert get_context_window("Claude Opus 4.1") == 200000
    assert get_context_window("Gemini 2.5 Pro") == 1000000

def test_get_primary_and_secondary_llm(monkeypatch):
    # Ensure placeholder keys trigger offline fallback gracefully
    monkeypatch.setenv("OPENAI_API_KEY", "your_openai_api_key_here")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "your_anthropic_api_key_here")

    primary_llm, context_win = get_primary_llm("openai", "gpt-4o")
    assert primary_llm is None
    assert context_win == 128000

    secondary_llm = get_secondary_llm("openai")
    assert secondary_llm is None
