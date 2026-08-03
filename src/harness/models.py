import os
from dataclasses import asdict, dataclass
from typing import Dict, List, Any, Optional, Tuple

# Model context window capacities in tokens
CONTEXT_WINDOW_CAPACITIES: Dict[str, int] = {
    "GPT-5.5": 128000,
    "GPT-5": 128000,
    "gpt-4o": 128000,
    "gpt-4o-mini": 128000,
    "GPT-5 nano": 128000,
    "o1-mini": 128000,
    "o3-mini": 128000,
    "Claude Opus 4.1": 200000,
    "Claude Sonnet 4": 200000,
    "claude-3-5-sonnet-latest": 200000,
    "claude-3-5-haiku-latest": 200000,
    "claude-3-opus-latest": 200000,
    "Gemini 2.5 Pro": 1000000,
    "Gemini 2.5 Flash": 1000000,
    "gemini-1.5-pro": 1000000,
    "gemini-1.5-flash": 1000000,
    "Gemini 2.5 Flash-Lite": 1000000,
    "grok-2-latest": 128000,
    "grok-beta": 128000
}

# Primary and Secondary Tiered Model Pairings
MODEL_PAIRS: Dict[str, Dict[str, Any]] = {
    "openai": {
        "primary": "gpt-4o",  # Fallback for GPT-5.5 / GPT-5
        "primary_options": ["GPT-5.5", "GPT-5", "gpt-4o", "o1-mini", "o3-mini"],
        "secondary": "gpt-4o-mini",  # Fallback for GPT-5 nano
        "secondary_options": ["GPT-5 nano", "gpt-4o-mini"],
        "context_window": 128000
    },
    "anthropic": {
        "primary": "claude-3-5-sonnet-latest",  # Fallback for Claude Opus 4.1 / Claude Sonnet 4
        "primary_options": ["Claude Opus 4.1", "Claude Sonnet 4", "claude-3-5-sonnet-latest"],
        "secondary": "claude-3-5-haiku-latest",  # Fallback for Claude Sonnet 4
        "secondary_options": ["Claude Sonnet 4", "claude-3-5-haiku-latest"],
        "context_window": 200000
    },
    "gemini": {
        "primary": "gemini-1.5-pro",  # Fallback for Gemini 2.5 Pro / Gemini 2.5 Flash
        "primary_options": ["Gemini 2.5 Pro", "Gemini 2.5 Flash", "gemini-1.5-pro"],
        "secondary": "gemini-1.5-flash",  # Fallback for Gemini 2.5 Flash-Lite
        "secondary_options": ["Gemini 2.5 Flash-Lite", "gemini-1.5-flash"],
        "context_window": 1000000
    },
    "grok": {
        "primary": "grok-2-latest",
        "primary_options": ["grok-2-latest"],
        "secondary": "grok-beta",
        "secondary_options": ["grok-beta"],
        "context_window": 128000
    }
}

SUPPORTED_PROVIDERS: Dict[str, Dict[str, Any]] = {
    "openai": {
        "name": "OpenAI",
        "env_key": "OPENAI_API_KEY",
        "models": ["gpt-4o-mini", "gpt-4o", "o1-mini", "o3-mini", "GPT-5.5", "GPT-5"],
        "default": "gpt-4o-mini"
    },
    "anthropic": {
        "name": "Anthropic Claude",
        "env_key": "ANTHROPIC_API_KEY",
        "models": ["claude-3-5-sonnet-latest", "claude-3-5-haiku-latest", "claude-3-opus-latest", "Claude Opus 4.1", "Claude Sonnet 4"],
        "default": "claude-3-5-sonnet-latest"
    },
    "gemini": {
        "name": "Google Gemini",
        "env_key": "GOOGLE_API_KEY",
        "models": ["gemini-1.5-flash", "gemini-1.5-pro", "gemini-2.0-flash", "Gemini 2.5 Pro", "Gemini 2.5 Flash"],
        "default": "gemini-1.5-flash"
    },
    "grok": {
        "name": "xAI Grok",
        "env_key": "XAI_API_KEY",
        "models": ["grok-2-latest", "grok-beta"],
        "default": "grok-2-latest"
    }
}


@dataclass(frozen=True)
class ModelRoleConfig:
    primary_provider: str
    primary_model_name: str
    primary_context_window: int
    secondary_provider: str
    secondary_model_name: str
    secondary_context_window: int


def get_model_role_config(memory_config: Optional[Any] = None) -> ModelRoleConfig:
    """Returns primary and secondary model selector metadata for role-aware routing."""
    if memory_config is None:
        from src.memory.config import load_memory_config

        memory_config = load_memory_config()

    primary = memory_config.primary_llm
    secondary = memory_config.secondary_llm
    return ModelRoleConfig(
        primary_provider=primary.provider,
        primary_model_name=primary.model_name,
        primary_context_window=primary.context_window,
        secondary_provider=secondary.provider,
        secondary_model_name=secondary.model_name,
        secondary_context_window=secondary.context_window,
    )

def get_model_catalog() -> Dict[str, Any]:
    """Returns catalog of supported providers, tiered pairs, and context windows."""
    result = dict(SUPPORTED_PROVIDERS)
    result["providers"] = SUPPORTED_PROVIDERS
    result["pairs"] = MODEL_PAIRS
    result["capacities"] = CONTEXT_WINDOW_CAPACITIES
    try:
        result["role_defaults"] = asdict(get_model_role_config())
    except Exception:
        result["role_defaults"] = {}
    return result


def is_valid_key(key_value: Optional[str]) -> bool:
    """Checks if an API key is present and not a placeholder."""
    return bool(key_value and not key_value.strip().startswith("your_"))

def get_context_window(model_name: str, provider: str = "openai") -> int:
    """Returns the context window token capacity for a specified model."""
    if model_name in CONTEXT_WINDOW_CAPACITIES:
        return CONTEXT_WINDOW_CAPACITIES[model_name]
    norm_provider = provider.lower().strip()
    if norm_provider in MODEL_PAIRS:
        return MODEL_PAIRS[norm_provider]["context_window"]
    return 128000

def get_model_instance(
    provider: str = "openai",
    model_name: str = "gpt-4o-mini",
    temperature: float = 0.7
) -> Optional[Any]:
    """
    Factory function instantiating standard LangChain chat models for
    OpenAI, Anthropic Claude, Google Gemini, and xAI Grok.
    Returns None if the provider API key is missing or set to placeholder.
    """
    norm_provider = provider.lower().strip()
    if norm_provider not in SUPPORTED_PROVIDERS:
        norm_provider = "openai"

    prov_config = SUPPORTED_PROVIDERS[norm_provider]
    env_var_name = prov_config["env_key"]
    api_key = os.getenv(env_var_name)

    if not is_valid_key(api_key):
        return None

    try:
        if norm_provider == "openai":
            from langchain_openai import ChatOpenAI
            # Map future models to current fallbacks if needed
            target_model = "gpt-4o" if model_name in ("GPT-5.5", "GPT-5") else ("gpt-4o-mini" if model_name == "GPT-5 nano" else model_name)
            return ChatOpenAI(model=target_model, temperature=temperature, api_key=api_key)

        elif norm_provider == "anthropic":
            try:
                from langchain_anthropic import ChatAnthropic
                target_model = "claude-3-5-sonnet-latest" if model_name in ("Claude Opus 4.1", "Claude Sonnet 4") else model_name
                return ChatAnthropic(model=target_model, temperature=temperature, api_key=api_key)
            except ImportError:
                return None

        elif norm_provider == "gemini":
            try:
                from langchain_google_genai import ChatGoogleGenerativeAI
                target_model = "gemini-1.5-pro" if model_name in ("Gemini 2.5 Pro", "Gemini 2.5 Flash") else ("gemini-1.5-flash" if model_name == "Gemini 2.5 Flash-Lite" else model_name)
                return ChatGoogleGenerativeAI(model=target_model, temperature=temperature, google_api_key=api_key)
            except ImportError:
                return None

        elif norm_provider == "grok":
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model=model_name,
                temperature=temperature,
                api_key=api_key,
                base_url="https://api.x.ai/v1"
            )

    except Exception as e:
        print(f"[Model Factory Warning] Failed to instantiate provider '{norm_provider}' with model '{model_name}': {e}")
        return None

    return None

def get_primary_llm(
    provider: str = "openai",
    model_name: Optional[str] = None,
    temperature: float = 0.7
) -> Tuple[Optional[Any], int]:
    """
    Returns Primary LLM instance (Planner / Reasoner) and its context window size in tokens.
    Compatibility wrapper around the role-aware LLM router.
    """
    from src.harness.llm_router import resolve_primary_llm

    route = resolve_primary_llm(provider=provider, model_name=model_name, temperature=temperature)
    return route.llm, route.selector.context_window

def get_secondary_llm(
    provider: str = "openai",
    secondary_model_name: Optional[str] = None,
    temperature: float = 0.3
) -> Optional[Any]:
    """
    Returns Secondary LLM instance for background memory tasks.
    Compatibility wrapper around the role-aware LLM router.
    """
    from src.harness.llm_router import resolve_secondary_llm

    route = resolve_secondary_llm(provider=provider, model_name=secondary_model_name, temperature=temperature)
    return route.llm


