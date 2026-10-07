"""Bounded, retrying LLM calls.

Every LLM request in an evaluation run goes through `call_llm`, which provides:
* a run-wide in-flight cap (`ProviderGate`) and an optional requests/second limit,
* a per-attempt timeout,
* retries with exponential backoff + jitter for transient failures (timeouts, connection
  errors, HTTP 429 and 5xx), honouring `Retry-After`,
* a shared "cool-down" so one 429 slows every concurrent caller, not just the one that saw it,
* immediate failure for permanent errors (4xx other than 429, programming errors),
* clean cancellation (`asyncio.CancelledError` is never swallowed).
"""

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx
import structlog

from app.providers.base import BaseLLMProvider
from app.providers.models import GenerationParams, LLMResponse

logger = structlog.get_logger(__name__)

TRANSIENT_STATUS = {408, 425, 429, 500, 502, 503, 504}


class LLMCallError(Exception):
    def __init__(self, kind: str, message: str, attempts: int):
        super().__init__(f"{kind}: {message}")
        self.kind = (
            kind  # timeout | rate_limited | server_error | connection | client_error | error
        )
        self.message = message
        self.attempts = attempts


@dataclass
class CallResult:
    response: LLMResponse
    attempts: int


class ProviderGate:
    """Concurrency + rate-limit guard shared by all calls of one run."""

    def __init__(
        self,
        max_inflight: int,
        requests_per_second: float = 0.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self._sem = asyncio.Semaphore(max(1, max_inflight))
        self._interval = 1.0 / requests_per_second if requests_per_second > 0 else 0.0
        self._next_slot = 0.0
        self._cooldown_until = 0.0
        self._lock = asyncio.Lock()
        self._clock = clock
        self._sleep = sleep
        self.inflight = 0
        self.max_observed_inflight = 0

    def cool_down(self, seconds: float) -> None:
        self._cooldown_until = max(self._cooldown_until, self._clock() + seconds)

    async def __aenter__(self) -> "ProviderGate":
        await self._sem.acquire()
        try:
            async with self._lock:
                now = self._clock()
                start = max(now, self._next_slot, self._cooldown_until)
                self._next_slot = start + self._interval
            if start > now:
                await self._sleep(start - now)
        except BaseException:
            self._sem.release()
            raise
        self.inflight += 1
        self.max_observed_inflight = max(self.max_observed_inflight, self.inflight)
        return self

    async def __aexit__(self, *exc) -> None:
        self.inflight -= 1
        self._sem.release()


def _classify(exc: BaseException) -> tuple[str, bool, float | None]:
    """-> (kind, retryable, retry_after_seconds)"""
    if isinstance(exc, asyncio.TimeoutError | httpx.TimeoutException):
        return "timeout", True, None
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        retry_after = None
        header = exc.response.headers.get("retry-after")
        if header:
            try:
                retry_after = max(0.0, float(header))
            except ValueError:
                retry_after = None
        if status == 429:
            return "rate_limited", True, retry_after
        if status in TRANSIENT_STATUS:
            return "server_error", True, retry_after
        return "client_error", False, None
    if isinstance(
        exc, httpx.ConnectError | httpx.ReadError | httpx.RemoteProtocolError | httpx.WriteError
    ):
        return "connection", True, None
    return "error", False, None


async def call_llm(
    provider: BaseLLMProvider,
    gate: ProviderGate,
    *,
    prompt: str,
    system_prompt: str | None = None,
    params: GenerationParams | None = None,
    timeout: float = 120.0,
    max_retries: int = 3,
    backoff_base: float = 1.0,
    backoff_max: float = 30.0,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> CallResult:
    attempts = 0
    while True:
        attempts += 1
        try:
            async with gate:
                response = await asyncio.wait_for(
                    provider.generate(prompt, system_prompt, params), timeout=timeout
                )
            return CallResult(response=response, attempts=attempts)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - classified below
            kind, retryable, retry_after = _classify(exc)
            message = str(exc) or exc.__class__.__name__
            if not retryable or attempts > max_retries:
                raise LLMCallError(kind, message, attempts) from exc
            delay = (
                retry_after
                if retry_after is not None
                else min(
                    backoff_max, backoff_base * (2 ** (attempts - 1)) * (0.5 + random.random() / 2)
                )
            )
            if kind == "rate_limited":
                gate.cool_down(delay)
            await logger.awarning(
                "LLM call failed; retrying", kind=kind, attempt=attempts, delay_s=round(delay, 3)
            )
            await sleep(delay)
