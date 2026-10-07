import time

import httpx
import structlog

from app.providers.base import BaseLLMProvider
from app.providers.models import GenerationParams, LLMResponse, ProviderConfig, TokenUsage

logger = structlog.get_logger(__name__)


class GroqProvider(BaseLLMProvider):
    """Groq provider implementation using httpx AsyncClient.

    Groq provides fast inference with various open-source models.
    This implementation uses the Groq Cloud API.
    """

    # Groq pricing (as of 2024) - approximate per 1M tokens
    PRICING = {
        "llama3-8b-8192": {"input": 0.05, "output": 0.08},
        "llama3-70b-8192": {"input": 0.59, "output": 0.79},
        "mixtral-8x7b-32768": {"input": 0.27, "output": 0.27},
        "gemma-7b-it": {"input": 0.07, "output": 0.07},
    }

    def __init__(self, config: ProviderConfig, model: str = "llama3-8b-8192"):
        super().__init__(config)
        self.model = model
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        """Lazy initialization of httpx AsyncClient."""
        if self._client is None:
            headers = {}
            if self.config.api_key:
                headers["Authorization"] = f"Bearer {self.config.api_key}"

            self._client = httpx.AsyncClient(
                base_url=self.config.base_url,
                timeout=self.config.timeout,
                headers=headers,
                limits=httpx.Limits(
                    max_connections=self.config.max_concurrent_requests,
                    max_keepalive_connections=self.config.max_concurrent_requests,
                ),
            )
        return self._client

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        params: GenerationParams | None = None,
    ) -> LLMResponse:
        """Generate a response using Groq API.

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

        # Build Groq API request (OpenAI-compatible format)
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": params.temperature,
        }

        if params.max_tokens:
            payload["max_tokens"] = params.max_tokens

        if params.top_p:
            payload["top_p"] = params.top_p

        if params.json_mode:
            payload["response_format"] = {"type": "json_object"}

        if params.frequency_penalty is not None:
            payload["frequency_penalty"] = params.frequency_penalty

        if params.presence_penalty is not None:
            payload["presence_penalty"] = params.presence_penalty

        try:
            response = await self.client.post("/openai/v1/chat/completions", json=payload)
            response.raise_for_status()
            data = response.json()

            latency_ms = (time.perf_counter() - start_time) * 1000

            # Extract content and token usage
            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})

            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)
            total_tokens = usage.get("total_tokens", 0)

            token_usage = TokenUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
            )

            await logger.adebug(
                "Groq generation completed",
                model=self.model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=latency_ms,
            )

            return LLMResponse(
                content=content,
                provider=self.provider_name,
                model=self.model,
                latency_ms=latency_ms,
                token_usage=token_usage,
                estimated_cost=self.estimate_cost(prompt_tokens, completion_tokens),
                raw_response=data,
            )

        except httpx.HTTPError as e:
            await logger.aerror(
                "Groq API request failed",
                model=self.model,
                error=str(e),
            )
            raise
        except Exception as e:
            await logger.aerror(
                "Unexpected error in Groq generation",
                model=self.model,
                error=str(e),
            )
            raise

    async def health_check(self) -> bool:
        """Check if Groq API is accessible."""
        try:
            response = await self.client.get("/v1/models")
            response.raise_for_status()
            return True
        except Exception as e:
            await logger.awarning(
                "Groq health check failed",
                error=str(e),
            )
            return False

    def estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        """Estimate cost based on Groq pricing."""
        pricing = self.PRICING.get(self.model, {"input": 0.05, "output": 0.08})
        input_cost = (prompt_tokens / 1_000_000) * pricing["input"]
        output_cost = (completion_tokens / 1_000_000) * pricing["output"]
        return input_cost + output_cost

    async def close(self) -> None:
        """Close the httpx client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
