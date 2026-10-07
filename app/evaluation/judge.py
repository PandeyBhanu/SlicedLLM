"""LLM-as-judge for pairwise comparison of two *generated outputs*.

Flow per judge call
-------------------
1. `build_judge_prompt` shows the judge: the test input, the expected behaviour, the rubric, and two
   responses labelled "Response A"/"Response B" (plus the instructions each one was generated from).
   It never shows version numbers, model names, latency, cost or token counts.
2. The judge must answer with one JSON object (provider JSON mode). `parse_verdict` extracts it and
   `JudgeVerdict` validates it against the rubric: exact criterion set, scores inside the scale,
   confidence in [0,1], and a winner consistent with the criterion scores.
3. Invalid output is retried, feeding the validation error back to the judge. After
   `max_attempts` the call raises `JudgeError`; no score is ever invented.
4. `normalize` maps a swapped call back to candidate terms; `combine_passes` merges the
   original-order and swapped-order calls into one result and derives confidence.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Literal

import structlog
from pydantic import BaseModel, Field, ValidationError, field_validator

from app.evaluation.calls import CallResult, LLMCallError, ProviderGate, call_llm
from app.providers.base import BaseLLMProvider
from app.providers.models import GenerationParams

logger = structlog.get_logger(__name__)

Winner = Literal["A", "B", "TIE"]
TIE_TOLERANCE = (
    0.25  # a judge "TIE" is accepted when the weighted scores differ by <= this (scale points)
)

JUDGE_SYSTEM_PROMPT = (
    "You are a strict, impartial evaluator of AI assistant responses. "
    "Judge only the content of the responses against the rubric. "
    "Ignore the order in which responses are presented and do not favour longer answers. "
    "Reply with a single JSON object and nothing else."
)


class JudgeError(Exception):
    def __init__(
        self,
        message: str,
        attempts: int,
        raw_response: str | None = None,
        kind: str = "invalid_output",
        usage: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.attempts = attempts
        self.raw_response = raw_response
        self.kind = kind
        self.usage = usage or {}


class CriterionScore(BaseModel):
    score_a: float
    score_b: float
    reason: str = ""


class JudgeVerdict(BaseModel):
    winner: Winner
    criteria: dict[str, CriterionScore]
    overall_score_a: float | None = None
    overall_score_b: float | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = ""

    @field_validator("winner", mode="before")
    @classmethod
    def _upper(cls, v: Any) -> Any:
        return v.strip().upper() if isinstance(v, str) else v


@dataclass
class RubricSpec:
    id: Any
    name: str
    version: int
    scale_min: int
    scale_max: int
    criteria: list[dict[str, Any]]

    @property
    def weights(self) -> dict[str, float]:
        return {c["name"]: float(c.get("weight", 1.0)) for c in self.criteria}


@dataclass
class JudgeConfig:
    provider: str
    model: str
    max_attempts: int = 3
    temperature: float = 0.0
    max_tokens: int = 1500
    include_prompts: bool = True
    position_strategy: Literal["both", "alternate", "none"] = "both"

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "max_attempts": self.max_attempts,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "include_prompts": self.include_prompts,
            "position_strategy": self.position_strategy,
        }


@dataclass
class NormalizedJudgement:
    """A validated judge call expressed in candidate terms (A = version A's output)."""

    pass_index: int
    swapped: bool
    winner: Winner
    score_a: float  # rubric-weighted, rubric scale
    score_b: float
    normalized_a: float  # 0..1
    normalized_b: float
    confidence: float
    reasoning: str
    criteria: dict[str, dict[str, Any]]  # name -> {score_a, score_b, reason}, candidate terms
    raw_score: dict[str, Any]  # validated JSON as returned (judge's own A/B positions)
    raw_response: str
    attempts: int
    prompt_tokens: int
    completion_tokens: int
    estimated_cost: float
    latency_ms: float


def build_judge_prompt(
    *,
    rubric: RubricSpec,
    input_text: str,
    expected_behavior: dict[str, Any],
    response_a: str,
    response_b: str,
    prompt_a: str | None = None,
    prompt_b: str | None = None,
) -> str:
    criteria_lines = "\n".join(
        f"- {c['name']} (weight {c.get('weight', 1.0)}): {c.get('description', '')}"
        for c in rubric.criteria
    )
    example_criteria = ",\n".join(
        f'    "{c["name"]}": {{"score_a": <{rubric.scale_min}-{rubric.scale_max}>, '
        f'"score_b": <{rubric.scale_min}-{rubric.scale_max}>, "reason": "<one sentence>"}}'
        for c in rubric.criteria
    )
    expected = (
        json.dumps(expected_behavior, ensure_ascii=False, indent=2)
        if expected_behavior
        else "(none provided)"
    )

    def section(label: str, prompt: str | None, response: str) -> str:
        parts = [f"### Response {label}"]
        if prompt is not None:
            parts.append(
                f"Instructions the assistant received for Response {label}:\n<<<\n{prompt}\n>>>"
            )
        parts.append(f"Response {label}:\n<<<\n{response}\n>>>")
        return "\n".join(parts)

    return f"""Compare two assistant responses to the same test input.

## Test input
<<<
{input_text}
>>>

## Expected behavior / reference notes
{expected}

## Rubric — score each criterion for BOTH responses, integers
{rubric.scale_min}-{rubric.scale_max} ({rubric.scale_max} is best)
{criteria_lines}

{section("A", prompt_a, response_a)}

{section("B", prompt_b, response_b)}

## Output format
Return ONLY this JSON object:
{{
  "winner": "A" | "B" | "TIE",
  "criteria": {{
{example_criteria}
  }},
  "overall_score_a": <number>,
  "overall_score_b": <number>,
  "confidence": <number between 0 and 1: how sure you are of the winner>,
  "reasoning": "<2-3 sentences justifying the winner>"
}}"""


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def extract_json_object(text: str) -> dict[str, Any]:
    """Parse the judge's reply as a JSON object. Tolerates code fences / surrounding prose only."""
    candidate = _FENCE.sub("", text.strip())
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        start, end = candidate.find("{"), candidate.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("response contains no JSON object") from None
        try:
            parsed = json.loads(candidate[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ValueError(f"response is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("JSON response must be an object")
    return parsed


def weighted_score(scores: dict[str, float], weights: dict[str, float]) -> float:
    total = sum(weights.values())
    return sum(scores[name] * w for name, w in weights.items()) / total


def parse_verdict(text: str, rubric: RubricSpec) -> JudgeVerdict:
    """Parse + validate. Raises ValueError with a message the judge can act on."""
    data = extract_json_object(text)
    try:
        verdict = JudgeVerdict.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        raise ValueError(
            f"schema error at {'.'.join(map(str, first['loc']))}: {first['msg']}"
        ) from exc

    expected = set(rubric.weights)
    got = set(verdict.criteria)
    if got != expected:
        raise ValueError(
            f"criteria must be exactly {sorted(expected)}; "
            f"missing={sorted(expected - got)} unexpected={sorted(got - expected)}"
        )
    for name, cs in verdict.criteria.items():
        for label, value in (("score_a", cs.score_a), ("score_b", cs.score_b)):
            if not (rubric.scale_min <= value <= rubric.scale_max):
                raise ValueError(
                    f"criteria.{name}.{label}={value} is outside "
                    f"{rubric.scale_min}-{rubric.scale_max}"
                )

    a, b = _weighted(verdict, rubric)
    diff = a - b
    if verdict.winner == "A" and not diff > 0:
        raise ValueError("winner is A but the criterion scores do not favour A")
    if verdict.winner == "B" and not diff < 0:
        raise ValueError("winner is B but the criterion scores do not favour B")
    if verdict.winner == "TIE" and abs(diff) > TIE_TOLERANCE:
        raise ValueError("winner is TIE but the criterion scores differ clearly")
    return verdict


def _weighted(verdict: JudgeVerdict, rubric: RubricSpec) -> tuple[float, float]:
    weights = rubric.weights
    a = weighted_score({n: verdict.criteria[n].score_a for n in weights}, weights)
    b = weighted_score({n: verdict.criteria[n].score_b for n in weights}, weights)
    return a, b


def normalize(
    verdict: JudgeVerdict,
    rubric: RubricSpec,
    *,
    swapped: bool,
    pass_index: int,
    raw_response: str,
    attempts: int,
    calls: list[CallResult],
) -> NormalizedJudgement:
    """Translate the judge's positions back to candidate terms and recompute scores ourselves."""
    a, b = _weighted(verdict, rubric)
    winner: Winner = verdict.winner
    criteria = {
        n: {"score_a": cs.score_a, "score_b": cs.score_b, "reason": cs.reason}
        for n, cs in verdict.criteria.items()
    }
    if swapped:
        a, b = b, a
        winner = {"A": "B", "B": "A", "TIE": "TIE"}[verdict.winner]  # type: ignore[assignment]
        criteria = {
            n: {"score_a": c["score_b"], "score_b": c["score_a"], "reason": c["reason"]}
            for n, c in criteria.items()
        }
    span = rubric.scale_max - rubric.scale_min
    usage = [c.response for c in calls]
    return NormalizedJudgement(
        pass_index=pass_index,
        swapped=swapped,
        winner=winner,
        score_a=a,
        score_b=b,
        normalized_a=(a - rubric.scale_min) / span,
        normalized_b=(b - rubric.scale_min) / span,
        confidence=verdict.confidence,
        reasoning=verdict.reasoning,
        criteria=criteria,
        raw_score=verdict.model_dump(),
        raw_response=raw_response,
        attempts=attempts,
        prompt_tokens=sum(r.token_usage.prompt_tokens for r in usage if r.token_usage),
        completion_tokens=sum(r.token_usage.completion_tokens for r in usage if r.token_usage),
        estimated_cost=sum(r.estimated_cost or 0.0 for r in usage),
        latency_ms=sum(r.latency_ms for r in usage),
    )


@dataclass
class CombinedJudgement:
    winner: Winner
    score_a: float
    score_b: float
    confidence: float
    position_consistent: bool


def combine_passes(passes: list[NormalizedJudgement]) -> CombinedJudgement:
    """Merge judge passes (one per presentation order) into the final comparison.

    * score = mean over passes.
    * winner: if the passes never contradict each other (no A-vs-B disagreement) take the
      decisive vote (or TIE if all tied); if they contradict, the judge is position-biased on this
      case, so the result is TIE and flagged inconsistent.
    * confidence = mean judge confidence x fraction of passes agreeing with the final winner.
    """
    if not passes:
        raise ValueError("combine_passes needs at least one judge pass")
    votes = {p.winner for p in passes}
    decisive = votes - {"TIE"}
    if len(decisive) > 1:
        winner: Winner = "TIE"
        consistent = False
    else:
        winner = next(iter(decisive)) if decisive else "TIE"  # type: ignore[assignment]
        consistent = True
    agreement = sum(1 for p in passes if p.winner == winner) / len(passes)
    mean_conf = sum(p.confidence for p in passes) / len(passes)
    return CombinedJudgement(
        winner=winner,
        score_a=sum(p.score_a for p in passes) / len(passes),
        score_b=sum(p.score_b for p in passes) / len(passes),
        confidence=round(mean_conf * agreement, 6),
        position_consistent=consistent,
    )


def plan_passes(strategy: str, case_key: str) -> list[bool]:
    """Which presentation orders to run, as `swapped` flags.

    both      -> [False, True]  (every case judged in both orders; 2x judge cost)
    alternate -> one pass, swapped for a deterministic half of cases (hash parity of the case id)
    none      -> [False]        (no position-bias mitigation)
    """
    if strategy == "both":
        return [False, True]
    if strategy == "alternate":
        return [hashlib.sha256(case_key.encode("utf-8")).digest()[0] % 2 == 1]
    return [False]


async def run_judge_pass(
    *,
    provider: BaseLLMProvider,
    gate: ProviderGate,
    rubric: RubricSpec,
    config: JudgeConfig,
    input_text: str,
    expected_behavior: dict[str, Any],
    output_a: str,
    output_b: str,
    prompt_a: str,
    prompt_b: str,
    swapped: bool,
    pass_index: int,
    timeout: float,
    max_retries: int,
    backoff_base: float,
    sleep=None,
) -> NormalizedJudgement:
    """One judge call with schema-validation retries. Raises `JudgeError` on failure."""
    first, second = (output_b, output_a) if swapped else (output_a, output_b)
    p_first, p_second = (prompt_b, prompt_a) if swapped else (prompt_a, prompt_b)
    base_prompt = build_judge_prompt(
        rubric=rubric,
        input_text=input_text,
        expected_behavior=expected_behavior,
        response_a=first,
        response_b=second,
        prompt_a=p_first if config.include_prompts else None,
        prompt_b=p_second if config.include_prompts else None,
    )
    params = GenerationParams(
        temperature=config.temperature, max_tokens=config.max_tokens, json_mode=True
    )
    calls: list[CallResult] = []
    last_raw: str | None = None
    last_error = "no attempts"
    prompt = base_prompt
    call_kwargs = {"sleep": sleep} if sleep else {}

    for attempt in range(1, config.max_attempts + 1):
        try:
            result = await call_llm(
                provider,
                gate,
                prompt=prompt,
                system_prompt=JUDGE_SYSTEM_PROMPT,
                params=params,
                timeout=timeout,
                max_retries=max_retries,
                backoff_base=backoff_base,
                **call_kwargs,
            )
        except LLMCallError as exc:
            raise JudgeError(
                f"judge call failed: {exc}", attempt, last_raw, kind=exc.kind, usage=_usage(calls)
            ) from exc
        calls.append(result)
        last_raw = result.response.content
        try:
            verdict = parse_verdict(last_raw, rubric)
            return normalize(
                verdict,
                rubric,
                swapped=swapped,
                pass_index=pass_index,
                raw_response=last_raw,
                attempts=attempt,
                calls=calls,
            )
        except ValueError as exc:
            last_error = str(exc)
            await logger.awarning("Invalid judge output", attempt=attempt, error=last_error)
            prompt = (
                f"{base_prompt}\n\nYour previous reply was rejected: {last_error}.\n"
                "Reply again with ONLY the corrected JSON object."
            )
    raise JudgeError(
        f"judge returned invalid output after {config.max_attempts} attempts: {last_error}",
        config.max_attempts,
        last_raw,
        kind="invalid_output",
        usage=_usage(calls),
    )


def _usage(calls: list[CallResult]) -> dict[str, Any]:
    rs = [c.response for c in calls]
    return {
        "prompt_tokens": sum(r.token_usage.prompt_tokens for r in rs if r.token_usage),
        "completion_tokens": sum(r.token_usage.completion_tokens for r in rs if r.token_usage),
        "estimated_cost": sum(r.estimated_cost or 0.0 for r in rs),
        "latency_ms": sum(r.latency_ms for r in rs),
    }
