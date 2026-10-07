import asyncio
import json
import re
from collections.abc import Callable
from typing import Any

import httpx

from app.evaluation.judge import JUDGE_SYSTEM_PROMPT
from app.providers.base import BaseLLMProvider
from app.providers.models import GenerationParams, LLMResponse, ProviderConfig, TokenUsage

Handler = Callable[[str, str | None, GenerationParams | None], str | Exception]

DEFAULT_CRITERIA = ["correctness", "relevance", "instruction_following", "clarity"]


def http_error(status: int, retry_after: str | None = None) -> httpx.HTTPStatusError:
    headers = {"retry-after": retry_after} if retry_after else {}
    request = httpx.Request("POST", "http://mock")
    return httpx.HTTPStatusError(
        f"HTTP {status}",
        request=request,
        response=httpx.Response(status, headers=headers, request=request),
    )


class ScriptedProvider(BaseLLMProvider):
    """A provider whose answers come from a Python function; records calls and concurrency."""

    def __init__(
        self, handler: Handler, *, name: str = "mock", model: str = "mock-model", delay: float = 0.0
    ):
        super().__init__(ProviderConfig(base_url="http://mock"))
        self.provider_name = name
        self.model = model
        self.handler = handler
        self.delay = delay
        self.calls: list[dict[str, Any]] = []
        self.inflight = 0
        self.max_inflight = 0
        self.closed = False

    async def generate(self, prompt, system_prompt=None, params=None) -> LLMResponse:
        self.inflight += 1
        self.max_inflight = max(self.max_inflight, self.inflight)
        self.calls.append({"prompt": prompt, "system": system_prompt, "params": params})
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            out = self.handler(prompt, system_prompt, params)
            if asyncio.iscoroutine(out):
                out = await out
            if isinstance(out, BaseException):
                raise out
            return LLMResponse(
                content=out,
                provider=self.provider_name,
                model=self.model,
                latency_ms=12.5,
                token_usage=TokenUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30),
                estimated_cost=0.001,
            )
        finally:
            self.inflight -= 1

    async def health_check(self) -> bool:
        return True

    def estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        return 0.0

    async def close(self) -> None:
        self.closed = True

    @property
    def judge_calls(self) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["system"] == JUDGE_SYSTEM_PROMPT]

    @property
    def candidate_calls(self) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["system"] != JUDGE_SYSTEM_PROMPT]


def builder_for(provider: BaseLLMProvider):
    return lambda name, model: provider


def verdict_json(
    a: float,
    b: float,
    *,
    winner: str | None = None,
    confidence: float = 0.8,
    criteria: list[str] | None = None,
    reasoning: str = "because",
) -> str:
    names = criteria or DEFAULT_CRITERIA
    if winner is None:
        winner = "A" if a > b else "B" if b > a else "TIE"
    return json.dumps(
        {
            "winner": winner,
            "criteria": {n: {"score_a": a, "score_b": b, "reason": f"{n} reason"} for n in names},
            "overall_score_a": a,
            "overall_score_b": b,
            "confidence": confidence,
            "reasoning": reasoning,
        }
    )


_RESP = {
    "A": re.compile(r"(?m)^Response A:\n<<<\n(.*?)\n>>>", re.S),
    "B": re.compile(r"(?m)^Response B:\n<<<\n(.*?)\n>>>", re.S),
}


def quality_of(text: str) -> int:
    m = re.search(r"QUALITY=(\d)", text)
    return int(m.group(1)) if m else 3


def honest_handler(judge_override: Callable[[str], str | Exception] | None = None) -> Handler:
    """Candidates answer with QUALITY=5 unless the prompt says 'badly' (QUALITY=2).
    The judge compares the QUALITY markers it sees in each position."""

    def handler(prompt: str, system: str | None, params) -> str | Exception:
        if system == JUDGE_SYSTEM_PROMPT:
            if judge_override:
                return judge_override(prompt)
            qa = quality_of(_RESP["A"].search(prompt).group(1))
            qb = quality_of(_RESP["B"].search(prompt).group(1))
            return verdict_json(qa, qb)
        return f"answer QUALITY={2 if 'badly' in prompt else 5}"

    return handler


# ---- API helpers -------------------------------------------------------------------------------
async def create_prompt_with_versions(client, name="p1", templates=None):
    templates = templates or [
        ("1.0.0", "Answer well: {{input}}"),
        ("1.1.0", "Answer badly: {{input}}"),
    ]
    r = await client.post("/api/v1/prompts", json={"name": name, "description": "d"})
    assert r.status_code == 201, r.text
    prompt_id = r.json()["id"]
    ids = []
    for semver, tmpl in templates:
        v = await client.post(
            f"/api/v1/prompts/{prompt_id}/versions",
            json={
                "semantic_version": semver,
                "template": tmpl,
                "provider_config": {"temperature": 0.2},
            },
        )
        assert v.status_code == 201, v.text
        ids.append(v.json()["id"])
    return prompt_id, ids


async def create_dataset_with_cases(client, name="ds1", n=3):
    d = await client.post("/api/v1/datasets", json={"name": name})
    assert d.status_code == 201, d.text
    ds_id = d.json()["id"]
    for i in range(n):
        c = await client.post(
            f"/api/v1/datasets/{ds_id}/cases",
            json={"input_text": f"question {i}", "expected_behavior": {"note": f"n{i}"}},
        )
        assert c.status_code == 201, c.text
    return ds_id


async def start_run(client, ds_id, a_id, b_id, **extra):
    body = {
        "dataset_id": ds_id,
        "prompt_version_a_id": a_id,
        "prompt_version_b_id": b_id,
        "provider": "ollama",
        "model": "m",
        **extra,
    }
    r = await client.post("/api/v1/evaluations/runs", json=body)
    assert r.status_code == 202, r.text
    return r.json()
