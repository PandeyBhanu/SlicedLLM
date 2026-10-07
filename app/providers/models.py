from typing import Any

from pydantic import BaseModel, Field


class TokenUsage(BaseModel):
    """Structured token usage metrics from LLM providers."""

    prompt_tokens: int = Field(default=0, description="Number of tokens in the input prompt")
    completion_tokens: int = Field(
        default=0, description="Number of tokens in the generated completion"
    )
    total_tokens: int = Field(default=0, description="Total tokens used in the request")


class LLMResponse(BaseModel):
    """Standardized response structure across all LLM providers."""

    content: str = Field(..., description="The generated text content from the LLM")
    provider: str = Field(..., description="The provider name (e.g., 'ollama', 'groq')")
    model: str = Field(..., description="The specific model used (e.g., 'llama3', 'mixtral')")
    latency_ms: float = Field(..., description="Latency in milliseconds")
    token_usage: TokenUsage | None = Field(default=None, description="Detailed token usage metrics")
    estimated_cost: float | None = Field(default=None, description="Estimated cost in USD")
    raw_response: dict[str, Any] | None = Field(
        default=None, description="Raw provider response for debugging"
    )


class ProviderConfig(BaseModel):
    """Configuration for LLM provider connections."""

    base_url: str = Field(..., description="Base URL for the provider API")
    api_key: str | None = Field(default=None, description="API key for authentication")
    timeout: float = Field(default=30.0, description="Request timeout in seconds")
    max_retries: int = Field(default=3, description="Maximum number of retry attempts")
    retry_delay: float = Field(default=1.0, description="Initial delay between retries in seconds")
    max_concurrent_requests: int = Field(default=10, description="Maximum concurrent requests")


class GenerationParams(BaseModel):
    """Parameters for LLM generation requests."""

    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="Sampling temperature")
    max_tokens: int | None = Field(default=None, ge=1, description="Maximum tokens to generate")
    top_p: float | None = Field(
        default=None, ge=0.0, le=1.0, description="Nucleus sampling threshold"
    )
    frequency_penalty: float | None = Field(
        default=None, ge=-2.0, le=2.0, description="Frequency penalty"
    )
    presence_penalty: float | None = Field(
        default=None, ge=-2.0, le=2.0, description="Presence penalty"
    )
    json_mode: bool = Field(default=False, description="Ask the provider for a JSON-only response")
