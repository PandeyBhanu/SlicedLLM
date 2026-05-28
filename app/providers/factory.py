from typing import Dict, Optional, Type
import structlog

from app.providers.base import BaseLLMProvider
from app.providers.groq import GroqProvider
from app.providers.models import ProviderConfig
from app.providers.ollama import OllamaProvider

logger = structlog.get_logger(__name__)


class ProviderRegistry:
    """Registry for available LLM providers.
    
    This class maintains a mapping of provider names to their implementation classes,
    allowing for dynamic provider instantiation and extensibility.
    """

    _providers: Dict[str, Type[BaseLLMProvider]] = {
        "ollama": OllamaProvider,
        "groq": GroqProvider,
    }

    @classmethod
    def register(cls, name: str, provider_class: Type[BaseLLMProvider]) -> None:
        """Register a new provider implementation.
        
        Args:
            name: The name to register the provider under
            provider_class: The provider class to register
        """
        cls._providers[name.lower()] = provider_class
        logger.info("Provider registered", provider=name)

    @classmethod
    def unregister(cls, name: str) -> None:
        """Unregister a provider.
        
        Args:
            name: The name of the provider to unregister
        """
        if name.lower() in cls._providers:
            del cls._providers[name.lower()]
            logger.info("Provider unregistered", provider=name)

    @classmethod
    def get_provider_class(cls, name: str) -> Optional[Type[BaseLLMProvider]]:
        """Get a provider class by name.
        
        Args:
            name: The name of the provider
            
        Returns:
            The provider class if found, None otherwise
        """
        return cls._providers.get(name.lower())

    @classmethod
    def list_providers(cls) -> list[str]:
        """List all registered provider names.
        
        Returns:
            List of registered provider names
        """
        return list(cls._providers.keys())


class ProviderFactory:
    """Factory for creating configured provider instances.
    
    This class handles the instantiation of provider instances with their
    specific configurations, providing a clean interface for the service layer.
    """

    def __init__(self):
        self._active_instances: Dict[str, BaseLLMProvider] = {}

    def create_provider(
        self,
        provider_name: str,
        config: ProviderConfig,
        model: Optional[str] = None,
    ) -> BaseLLMProvider:
        """Create a new provider instance.
        
        Args:
            provider_name: The name of the provider to create
            config: The configuration for the provider
            model: Optional model name (provider-specific)
            
        Returns:
            An instance of the requested provider
            
        Raises:
            ValueError: If the provider is not registered
        """
        provider_class = ProviderRegistry.get_provider_class(provider_name)
        if provider_class is None:
            available = ", ".join(ProviderRegistry.list_providers())
            raise ValueError(
                f"Provider '{provider_name}' not found. Available providers: {available}"
            )

        # Create instance with model-specific parameters
        if model:
            instance = provider_class(config, model=model)
        else:
            instance = provider_class(config)

        logger.info(
            "Provider instance created",
            provider=provider_name,
            model=model or "default",
        )

        return instance

    def get_or_create_provider(
        self,
        provider_name: str,
        config: ProviderConfig,
        model: Optional[str] = None,
    ) -> BaseLLMProvider:
        """Get an existing provider instance or create a new one.
        
        This method implements a simple caching mechanism to reuse provider
        instances when the same configuration is requested.
        
        Args:
            provider_name: The name of the provider
            config: The configuration for the provider
            model: Optional model name
            
        Returns:
            A provider instance (cached or new)
        """
        cache_key = f"{provider_name}:{model or 'default'}"
        
        if cache_key not in self._active_instances:
            self._active_instances[cache_key] = self.create_provider(
                provider_name, config, model
            )
        
        return self._active_instances[cache_key]

    async def close_all(self) -> None:
        """Close all active provider instances.
        
        This method should be called during application shutdown to ensure
        proper cleanup of resources (e.g., closing httpx clients).
        """
        for instance in self._active_instances.values():
            if hasattr(instance, "close"):
                await instance.close()
        
        self._active_instances.clear()
        logger.info("All provider instances closed")

    def clear_cache(self) -> None:
        """Clear the provider instance cache without closing instances.
        
        This is useful for forcing fresh instances to be created.
        """
        self._active_instances.clear()
        logger.info("Provider instance cache cleared")


# Global factory instance for application-wide use
global_provider_factory = ProviderFactory()
