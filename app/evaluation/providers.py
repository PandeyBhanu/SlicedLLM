from collections.abc import Callable

from app.core.config import settings
from app.core.exceptions import ValidationError
from app.providers import ProviderConfig, ProviderRegistry, global_provider_factory
from app.providers.base import BaseLLMProvider

ProviderBuilder = Callable[[str, str], BaseLLMProvider]


def default_provider_builder(provider: str, model: str) -> BaseLLMProvider:
    """Build a provider from environment settings. One instance per (run, provider, model)."""
    name = provider.lower()
    if ProviderRegistry.get_provider_class(name) is None:
        raise ValidationError(
            f"Unknown provider '{provider}'. "
            f"Available: {', '.join(ProviderRegistry.list_providers())}"
        )
    if name == "groq":
        cfg = ProviderConfig(
            base_url=settings.GROQ_BASE_URL,
            api_key=settings.GROQ_API_KEY,
            timeout=settings.GROQ_TIMEOUT,
            max_concurrent_requests=settings.GROQ_MAX_CONCURRENT_REQUESTS,
        )
    else:
        cfg = ProviderConfig(
            base_url=settings.OLLAMA_BASE_URL,
            timeout=settings.OLLAMA_TIMEOUT,
            max_concurrent_requests=settings.OLLAMA_MAX_CONCURRENT_REQUESTS,
        )
    return global_provider_factory.create_provider(name, cfg, model)
