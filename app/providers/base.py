from abc import ABC, abstractmethod

import structlog

from app.providers.models import GenerationParams, LLMResponse, ProviderConfig

logger = structlog.get_logger(__name__)


class BaseLLMProvider(ABC):
    """Abstract base class for all LLM providers.

    All provider implementations must inherit from this class and implement
    the generate method with a standardized async interface.
    """

    def __init__(self, config: ProviderConfig):
        self.config = config
        self.provider_name = self.__class__.__name__.replace("Provider", "").lower()

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        params: GenerationParams | None = None,
    ) -> LLMResponse:
        """Generate a response from the LLM.

        Args:
            prompt: The user prompt to send to the LLM
            system_prompt: Optional system prompt to guide behavior
            params: Optional generation parameters (temperature, max_tokens, etc.)

        Returns:
            LLMResponse: Standardized response with content, latency, and metadata
        """
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the provider is accessible and healthy.

        Returns:
            bool: True if provider is healthy, False otherwise
        """
        pass

    @abstractmethod
    def estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        """Estimate the cost of a generation request.

        Args:
            prompt_tokens: Number of tokens in the prompt
            completion_tokens: Number of tokens in the completion

        Returns:
            float: Estimated cost in USD
        """
        pass

    async def close(self) -> None:
        """Release network resources. Providers with clients override this."""
        return None
