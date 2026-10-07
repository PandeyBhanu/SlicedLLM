import asyncio

import httpx
import pytest

from app.evaluation.calls import LLMCallError, ProviderGate, call_llm
from tests.helpers import ScriptedProvider, http_error


class Sleeper:
    """Injectable sleep that records requested delays instead of waiting."""

    def __init__(self):
        self.delays = []

    async def __call__(self, seconds):
        self.delays.append(seconds)


def sequence(*items):
    it = iter(items)
    return lambda prompt, system, params: next(it)


async def run(provider, **kw):
    sleeper = kw.pop("sleeper", None) or Sleeper()
    gate = kw.pop("gate", None) or ProviderGate(4)
    result = await call_llm(provider, gate, prompt="hi", sleep=sleeper, backoff_base=1.0, **kw)
    return result, sleeper


async def test_success_first_try():
    p = ScriptedProvider(sequence("ok"))
    result, sleeper = await run(p)
    assert result.response.content == "ok" and result.attempts == 1 and sleeper.delays == []


async def test_retries_429_then_succeeds_and_honours_retry_after():
    p = ScriptedProvider(sequence(http_error(429, retry_after="7"), "ok"))
    gate_sleeper = Sleeper()
    gate = ProviderGate(2, sleep=gate_sleeper)
    result, sleeper = await run(p, gate=gate)
    assert result.attempts == 2 and sleeper.delays == [7.0]
    assert (
        len(gate_sleeper.delays) == 1 and gate_sleeper.delays[0] > 6
    )  # the retry waited out the shared cool-down
    assert gate._cooldown_until > 0  # other callers are slowed down too


@pytest.mark.parametrize("status", [500, 502, 503, 504])
async def test_retries_5xx(status):
    p = ScriptedProvider(sequence(http_error(status), http_error(status), "ok"))
    result, sleeper = await run(p)
    assert result.attempts == 3 and len(sleeper.delays) == 2
    assert sleeper.delays[1] > sleeper.delays[0] * 0.9  # exponential backoff (with jitter)


async def test_retries_timeouts_and_connection_errors():
    p = ScriptedProvider(sequence(httpx.ReadTimeout("slow"), httpx.ConnectError("down"), "ok"))
    result, _ = await run(p)
    assert result.attempts == 3


async def test_gives_up_after_max_retries():
    p = ScriptedProvider(sequence(*[http_error(503)] * 10))
    with pytest.raises(LLMCallError) as exc:
        await run(p, max_retries=2)
    assert exc.value.kind == "server_error" and exc.value.attempts == 3
    assert len(p.calls) == 3


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
async def test_client_errors_are_not_retried(status):
    p = ScriptedProvider(sequence(http_error(status), "never"))
    with pytest.raises(LLMCallError) as exc:
        await run(p)
    assert exc.value.kind == "client_error" and exc.value.attempts == 1 and len(p.calls) == 1


async def test_programming_errors_are_not_retried():
    p = ScriptedProvider(sequence(ValueError("bug"), "never"))
    with pytest.raises(LLMCallError) as exc:
        await run(p)
    assert exc.value.kind == "error" and len(p.calls) == 1


async def test_per_attempt_timeout_then_retry():
    attempts = {"n": 0}

    async def handler(prompt, system, params):
        attempts["n"] += 1
        if attempts["n"] == 1:
            await asyncio.sleep(5)
        return "fast"

    p = ScriptedProvider(handler)
    result, _ = await run(p, timeout=0.05)
    assert result.response.content == "fast" and result.attempts == 2


async def test_timeout_exhaustion_reports_timeout():
    async def handler(prompt, system, params):
        await asyncio.sleep(5)

    with pytest.raises(LLMCallError) as exc:
        await run(ScriptedProvider(handler), timeout=0.02, max_retries=1)
    assert exc.value.kind == "timeout" and exc.value.attempts == 2


async def test_cancellation_propagates_and_releases_the_gate():
    gate = ProviderGate(1)
    started = asyncio.Event()

    async def handler(prompt, system, params):
        started.set()
        await asyncio.sleep(30)

    task = asyncio.create_task(call_llm(ScriptedProvider(handler), gate, prompt="x"))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert gate.inflight == 0
    result, _ = await run(ScriptedProvider(sequence("after")), gate=gate)  # slot is free again
    assert result.response.content == "after"


async def test_gate_caps_inflight_requests():
    p = ScriptedProvider(lambda *a: "ok", delay=0.03)
    gate = ProviderGate(3)
    await asyncio.gather(*(call_llm(p, gate, prompt=str(i)) for i in range(15)))
    assert p.max_inflight == 3 and gate.max_observed_inflight == 3 and len(p.calls) == 15


async def test_rate_limiter_spaces_requests():
    times = []
    clock_now = {"t": 0.0}
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)
        clock_now["t"] += s

    gate = ProviderGate(10, requests_per_second=2.0, clock=lambda: clock_now["t"], sleep=fake_sleep)
    ScriptedProvider(lambda *a: "ok")
    for _ in range(4):
        async with gate:
            times.append(clock_now["t"])
    assert [round(t, 2) for t in times] == [0.0, 0.5, 1.0, 1.5]
