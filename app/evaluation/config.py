from dataclasses import asdict, dataclass
from typing import Any

from app.core.config import settings


@dataclass
class RunConfig:
    """Everything that shapes how a run executes. Stored on the run row (`config` JSONB)."""

    case_concurrency: int = 4  # cases processed at once
    max_inflight_requests: int = 8  # LLM requests in flight at once (candidates + judge)
    requests_per_second: float = 0.0  # 0 = unlimited
    call_timeout_s: float = 120.0
    max_retries: int = 3
    backoff_base_s: float = 1.0
    judge_max_attempts: int = 3
    judge_position_strategy: str = "both"  # both | alternate | none
    judge_include_prompts: bool = True
    judge_temperature: float = 0.0

    @classmethod
    def from_overrides(cls, overrides: dict[str, Any] | None = None) -> "RunConfig":
        base = cls(
            case_concurrency=settings.EVALUATION_CASE_CONCURRENCY,
            max_inflight_requests=settings.EVALUATION_MAX_INFLIGHT_REQUESTS,
            requests_per_second=settings.EVALUATION_REQUESTS_PER_SECOND,
            call_timeout_s=settings.EVALUATION_CALL_TIMEOUT,
            max_retries=settings.EVALUATION_MAX_RETRIES,
            backoff_base_s=settings.EVALUATION_BACKOFF_BASE,
            judge_max_attempts=settings.JUDGE_MAX_ATTEMPTS,
        )
        for key, value in (overrides or {}).items():
            if value is not None and hasattr(base, key):
                setattr(base, key, value)
        return base

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunConfig":
        known = {k: v for k, v in (data or {}).items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
