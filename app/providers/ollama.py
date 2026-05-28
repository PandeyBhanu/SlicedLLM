import time
from typing import Optional
import httpx
import structlog

from app.providers.base import BaseLLMProvider
from app.providers.models import GenerationParams, LLMResponse, ProviderConfig, TokenUsage

logger = structlog.get_logger(__name__)


class OllamaProvider(BaseLLMProvider):
    """Ollama provider implementation using httpx AsyncClient.
    
    Ollama is a local LLM provider that runs on localhost or a specified host.
    This implementation uses the Ollama REST API.
    """

    # Ollama pricing is effectively zero for local models, but we can track token usage
    TOKEN_COST_PER_1K = 0.0  # Local models are free

    def __init__(self, config: ProviderConfig, model: str = "llama3"):
        super().__init__(config)
        self.model = model
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def client(self) -> httpx.AsyncClient:
        """Lazy initialization of httpx AsyncClient."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.config.base_url,
                timeout=self.config.timeout,
                limits=httpx.Limits(
                    max_connections=self.config.max_concurrent_requests,
                    max_keepalive_connections=self.config.max_concurrent_requests,
                ),
            )
        return self._client

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        params: Optional[GenerationParams] = None,
    ) -> LLMResponse:
        """Generate a response using Ollama API.
        
        Args:
            prompt: The user prompt
            system_prompt: Optional system prompt
            params: Generation parameters
            
        Returns:
            LLMResponse: Standardized response
        """
        if params is None:
            params = GenerationParams()

        start_time = time.perf_counter()

        # Build Ollama API request
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": params.temperature,
            },
        }

        if system_prompt:
            payload["system"] = system_prompt

        if params.max_tokens:
            payload["options"]["num_predict"] = params.max_tokens

        if params.top_p:
            payload["options"]["top_p"] = params.top_p

        try:
            response = await self.client.post("/api/generate", json=payload)
            response.raise_for_status()
            data = response.json()

            latency_ms = (time.perf_counter() - start_time) * 1000

            # Extract token usage from Ollama response
            prompt_tokens = data.get("prompt_eval_count", 0)
            completion_tokens = data.get("eval_count", 0)
            total_tokens = prompt_tokens + completion_tokens

            token_usage = TokenUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
            )

            await logger.adebug(
                "Ollama generation completed",
                model=self.model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=latency_ms,
            )

            return LLMResponse(
                content=data.get("response", ""),
                provider=self.provider_name,
                model=self.model,
                latency_ms=latency_ms,
                token_usage=token_usage,
                estimated_cost=self.estimate_cost(prompt_tokens, completion_tokens),
                raw_response=data,
            )

        except httpx.HTTPError as e:
            await logger.aerror(
                "Ollama API request failed",
                model=self.model,
                error=str(e),
            )
            raise
        except Exception as e:
            await logger.aerror(
                "Unexpected error in Ollama generation",
                model=self.model,
                error=str(e),
            )
            raise

    async def health_check(self) -> bool:
        """Check if Ollama is accessible."""
        try:
            response = await self.client.get("/api/tags")
            response.raise_for_status()
            return True
        except Exception as e:
            await logger.awarning(
                "Ollama health check failed",
                error=str(e),
            )
            return False

    def estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        """Estimate cost (zero for local Ollama models)."""
        return 0.0

    async def close(self) -> None:
        """Close the httpx client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
