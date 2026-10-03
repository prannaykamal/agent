from dataclasses import dataclass
from typing import Any, Literal, Mapping, Optional, Tuple

from src.harness.models import (
    MODEL_PAIRS,
    SUPPORTED_PROVIDERS,
    get_active_provider,
    get_context_window,
    get_model_instance,
)


ModelRole = Literal["primary", "secondary"]


@dataclass(frozen=True)
class LLMSelector:
    role: ModelRole
    provider: str
    model_name: str
    temperature: float
    context_window: int
    source: str


@dataclass(frozen=True)
class LLMRouteResult:
    selector: LLMSelector
    llm: Optional[Any]
    available: bool
    fallback_used: bool
    error: Optional[str] = None


def _normalize_provider_with_fallback(provider: Optional[str]) -> Tuple[str, bool]:
    raw = (provider or "").strip().lower()
    if not raw:
        return get_active_provider(), False
    if raw == "xai":
        return "grok", False
    if raw in SUPPORTED_PROVIDERS:
        return raw, False
    return get_active_provider(), True


def normalize_provider(provider: Optional[str]) -> str:
    normalized, _ = _normalize_provider_with_fallback(provider)
    return normalized


def normalize_model_name(provider: str, model_name: Optional[str], role: ModelRole) -> str:
    normalized_provider = normalize_provider(provider)
    requested = (model_name or "").strip()
    if requested:
        return requested
    provider_defaults = MODEL_PAIRS.get(normalized_provider, {})
    return str(provider_defaults.get(role, "gpt-4o-mini"))


def resolve_llm_selector(
    role: ModelRole,
    provider: Optional[str] = None,
    model_name: Optional[str] = None,
    temperature: Optional[float] = None,
    source: str = "runtime",
) -> LLMSelector:
    normalized_provider = normalize_provider(provider)
    normalized_model = normalize_model_name(normalized_provider, model_name, role)
    resolved_temperature = temperature if temperature is not None else (0.7 if role == "primary" else 0.3)
    return LLMSelector(
        role=role,
        provider=normalized_provider,
        model_name=normalized_model,
        temperature=resolved_temperature,
        context_window=get_context_window(model_name=normalized_model, provider=normalized_provider),
        source=source,
    )


def _resolve_route(
    role: ModelRole,
    provider: Optional[str],
    model_name: Optional[str],
    temperature: Optional[float],
    source: str,
) -> LLMRouteResult:
    _, provider_fallback = _normalize_provider_with_fallback(provider)
    selector = resolve_llm_selector(
        role=role,
        provider=provider,
        model_name=model_name,
        temperature=temperature,
        source=source,
    )
    try:
        llm = get_model_instance(
            provider=selector.provider,
            model_name=selector.model_name,
            temperature=selector.temperature,
        )
        return LLMRouteResult(
            selector=selector,
            llm=llm,
            available=llm is not None,
            fallback_used=provider_fallback,
            error=None if llm is not None else "LLM unavailable",
        )
    except Exception as exc:
        return LLMRouteResult(
            selector=selector,
            llm=None,
            available=False,
            fallback_used=provider_fallback,
            error=str(exc),
        )


def resolve_primary_llm(
    provider: Optional[str] = None,
    model_name: Optional[str] = None,
    temperature: Optional[float] = None,
    source: str = "chat",
) -> LLMRouteResult:
    return _resolve_route(
        role="primary",
        provider=provider,
        model_name=model_name,
        temperature=temperature,
        source=source,
    )


def resolve_secondary_llm(
    provider: Optional[str] = None,
    model_name: Optional[str] = None,
    temperature: Optional[float] = None,
    source: str = "memory_worker",
) -> LLMRouteResult:
    return _resolve_route(
        role="secondary",
        provider=provider,
        model_name=model_name,
        temperature=temperature,
        source=source,
    )


def resolve_secondary_from_job_payload(payload: Mapping[str, Any]) -> LLMRouteResult:
    models = payload.get("models", {})
    if not isinstance(models, Mapping):
        models = {}
    return resolve_secondary_llm(
        provider=models.get("secondary_provider"),
        model_name=models.get("secondary_model_name"),
        source="memory_job_payload",
    )
