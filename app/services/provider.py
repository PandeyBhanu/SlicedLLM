import asyncio
import re
import time
from typing import Any, Dict, List, Optional
import httpx
import structlog

from app.core.exceptions import ProviderError

logger = structlog.get_logger(__name__)


class LLMResponse:
    """Standardized response container across LLM providers."""

    def __init__(
        self,
        content: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: float,
        estimated_cost: float,
    ):
        self.content = content
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = prompt_tokens + completion_tokens
        self.latency_ms = latency_ms
        self.estimated_cost = estimated_cost

    def to_dict(self) -> Dict[str, Any]:
        return {
            "content": self.content,
            "token_usage": {
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "total_tokens": self.total_tokens,
            },
            "latency_ms": self.latency_ms,
            "estimated_cost": self.estimated_cost,
        }


class ProviderService:
    """Interacts with LLM APIs and orchestrates template assembly."""

    PRICING = {
        "gpt-4o": {"input": 5.0 / 1_000_000, "output": 15.0 / 1_000_000},  # $ per token
        "claude-3-5-sonnet": {"input": 3.0 / 1_000_000, "output": 15.0 / 1_000_000},
    }

    def compile_template(self, template: str, variables: Dict[str, Any]) -> str:
        """Substitute values inside double curly braces (e.g., {{name}})."""
        pattern = r"\{\{\s*(\w+)\s*\}\}"
        
        def replace(match: re.Match) -> str:
            var_name = match.group(1)
            if var_name not in variables:
                # Keep original placeholder if not provided, or raise Error. 
                # For safety, let's keep it or default to empty.
                return f"[{var_name} is missing]"
            return str(variables[var_name])

        return re.sub(pattern, replace, template)

    async def execute_prompt(
        self,
        provider: str,
        model: str,
        compiled_text: str,
        config: Dict[str, Any],
    ) -> LLMResponse:
        """Simulate or route asynchronous prompt requests to upstream providers.
        
        In production, this hooks up to openai/anthropic async clients.
        Here we implement a robust simulation to allow offline tests to execute with deterministic, high-fidelity responses.
        """
        start_time = time.perf_counter()
        
        # Log request out
        await logger.adebug(
            "Executing prompt upstream",
            provider=provider,
            model=model,
            config=config,
        )

        try:
            # Simulate network latency (between 100ms - 400ms)
            await asyncio.sleep(0.15)
            
            # Simple heuristic text responder
            if "hello" in compiled_text.lower() or "name" in compiled_text.lower():
                content = f"[Model Response: {model}] Hello! It is wonderful to meet you. I'm ready to assist."
            elif "sentiment" in compiled_text.lower():
                content = f"[Model Response: {model}] Positive. The reasoning is clear and carries upbeat tonality."
            else:
                content = f"[Model Response: {model}] Successfully processed the compiled prompt input: '{compiled_text[:60]}...'"

            # Calculate token count
            # 1 token roughly = 4 characters for mock calculation
            prompt_tokens = max(1, len(compiled_text) // 4)
            completion_tokens = max(1, len(content) // 4)
            
            # Determine pricing
            pricing = self.PRICING.get(model, {"input": 0.000002, "output": 0.000006})
            estimated_cost = (prompt_tokens * pricing["input"]) + (completion_tokens * pricing["output"])
            
            latency_ms = (time.perf_counter() - start_time) * 1000

            return LLMResponse(
                content=content,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=round(latency_ms, 2),
                estimated_cost=round(estimated_cost, 6),
            )
            
        except Exception as e:
            await logger.aerror("LLM Provider call failed", provider=provider, model=model, error=str(e))
            raise ProviderError(
                message=f"Failed to communicate with provider {provider}.",
                details={"model": model, "reason": str(e)},
            )
global_provider_service = ProviderService()
