import pytest
from src.harness.models import get_model_catalog, get_model_instance, is_valid_key

def test_model_catalog():
    catalog = get_model_catalog()
    assert "openai" in catalog
    assert "anthropic" in catalog
    assert "gemini" in catalog
    assert "grok" in catalog

    assert "gpt-4o-mini" in catalog["openai"]["models"]
    assert "claude-3-5-sonnet-latest" in catalog["anthropic"]["models"]
    assert "gemini-1.5-flash" in catalog["gemini"]["models"]
    assert "grok-2-latest" in catalog["grok"]["models"]

def test_key_validation():
    assert is_valid_key("sk-proj-12345") is True
    assert is_valid_key(None) is False
    assert is_valid_key("") is False
    assert is_valid_key("your_openai_api_key_here") is False

def test_model_factory_fallback(monkeypatch):
    # Ensure API keys are set to placeholder to test fallback handling
    monkeypatch.setenv("OPENAI_API_KEY", "your_openai_api_key_here")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "your_anthropic_api_key_here")
    monkeypatch.setenv("GOOGLE_API_KEY", "your_google_gemini_api_key_here")
    monkeypatch.setenv("XAI_API_KEY", "your_xai_grok_api_key_here")

    assert get_model_instance("openai", "gpt-4o-mini") is None
    assert get_model_instance("anthropic", "claude-3-5-sonnet-latest") is None
    assert get_model_instance("gemini", "gemini-1.5-flash") is None
    assert get_model_instance("grok", "grok-2-latest") is None
