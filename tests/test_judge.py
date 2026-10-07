import json
import uuid

import pytest

from app.evaluation.calls import ProviderGate
from app.evaluation.judge import (
    JUDGE_SYSTEM_PROMPT,
    JudgeConfig,
    JudgeError,
    RubricSpec,
    build_judge_prompt,
    combine_passes,
    extract_json_object,
    normalize,
    parse_verdict,
    plan_passes,
    run_judge_pass,
)
from app.evaluation.rubrics import DEFAULT_CRITERIA
from tests.helpers import DEFAULT_CRITERIA as NAMES
from tests.helpers import ScriptedProvider, http_error, verdict_json

RUBRIC = RubricSpec(
    id=uuid.uuid4(), name="r", version=3, scale_min=1, scale_max=5, criteria=DEFAULT_CRITERIA
)


def verdict_dict(a=4, b=2, **over):
    d = json.loads(verdict_json(a, b))
    d.update(over)
    return d


# ---- parsing / validation ---------------------------------------------------------------------
def test_extracts_plain_fenced_and_wrapped_json():
    raw = verdict_json(4, 2)
    assert extract_json_object(raw)["winner"] == "A"
    assert extract_json_object(f"```json\n{raw}\n```")["winner"] == "A"
    assert extract_json_object(f"Sure! Here is my verdict: {raw} Hope it helps.")["winner"] == "A"


@pytest.mark.parametrize("raw", ["", "no json here", "{broken", "[1, 2]", '"just a string"'])
def test_non_object_output_is_rejected(raw):
    with pytest.raises(ValueError):
        extract_json_object(raw)


def test_valid_verdict_parses():
    v = parse_verdict(verdict_json(4, 2, confidence=0.7), RUBRIC)
    assert v.winner == "A" and v.confidence == 0.7 and set(v.criteria) == set(NAMES)


def test_winner_is_case_insensitive():
    assert parse_verdict(json.dumps(verdict_dict(winner="a")), RUBRIC).winner == "A"


@pytest.mark.parametrize(
    "mutate, fragment",
    [
        (lambda d: d.update(winner="C"), "winner"),
        (lambda d: d.pop("winner"), "winner"),
        (lambda d: d.update(confidence=1.5), "confidence"),
        (lambda d: d.update(confidence=-0.1), "confidence"),
        (lambda d: d.update(confidence="high"), "confidence"),
        (lambda d: d["criteria"].pop("clarity"), "missing"),
        (
            lambda d: d["criteria"].update(extra={"score_a": 3, "score_b": 3, "reason": ""}),
            "unexpected",
        ),
        (lambda d: d["criteria"]["clarity"].update(score_a=9), "outside"),
        (lambda d: d["criteria"]["clarity"].update(score_b=0), "outside"),
        (lambda d: d["criteria"]["clarity"].update(score_a="good"), "score_a"),
        (lambda d: d.update(winner="B"), "do not favour B"),
        (lambda d: d.update(winner="TIE"), "TIE"),
    ],
)
def test_invalid_verdicts_are_rejected(mutate, fragment):
    d = verdict_dict(5, 1)
    mutate(d)
    with pytest.raises(ValueError) as exc:
        parse_verdict(json.dumps(d), RUBRIC)
    assert fragment in str(exc.value)


def test_judge_claiming_a_when_scores_favour_b_is_rejected():
    with pytest.raises(ValueError):
        parse_verdict(verdict_json(1, 5, winner="A"), RUBRIC)


def test_tie_with_equal_scores_is_valid():
    assert parse_verdict(verdict_json(3, 3), RUBRIC).winner == "TIE"


# ---- prompt construction -----------------------------------------------------------------------
def test_judge_prompt_shows_outputs_but_no_identifying_metadata():
    prompt = build_judge_prompt(
        rubric=RUBRIC,
        input_text="INPUT-X",
        expected_behavior={"note": "NOTE-Y"},
        response_a="OUT-ONE",
        response_b="OUT-TWO",
        prompt_a="PROMPT-ONE",
        prompt_b="PROMPT-TWO",
    )
    for needle in ("INPUT-X", "NOTE-Y", "OUT-ONE", "OUT-TWO", "PROMPT-ONE", "correctness"):
        assert needle in prompt
    for forbidden in ("latency", "cost", "tokens", "1.0.0", "gpt", "llama", "version"):
        assert forbidden not in prompt.lower().replace("criterion", "")


def test_judge_prompt_can_hide_the_generating_prompts():
    prompt = build_judge_prompt(
        rubric=RUBRIC, input_text="i", expected_behavior={}, response_a="a", response_b="b"
    )
    assert "Instructions the assistant received" not in prompt and "(none provided)" in prompt


# ---- normalization / position swapping ---------------------------------------------------------
def norm(verdict_str, swapped, idx=0):
    v = parse_verdict(verdict_str, RUBRIC)
    return normalize(
        v, RUBRIC, swapped=swapped, pass_index=idx, raw_response=verdict_str, attempts=1, calls=[]
    )


def test_normalization_without_swap_keeps_positions():
    n = norm(verdict_json(4, 2), swapped=False)
    assert n.winner == "A" and n.score_a == pytest.approx(4) and n.score_b == pytest.approx(2)
    assert n.normalized_a == pytest.approx(0.75) and n.normalized_b == pytest.approx(0.25)


def test_normalization_maps_swapped_pass_back_to_candidates():
    # The judge saw candidate B in position A and gave it 4; candidate A (position B) got 2.
    n = norm(verdict_json(4, 2), swapped=True)
    assert n.winner == "B"
    assert n.score_a == pytest.approx(2) and n.score_b == pytest.approx(4)
    assert n.criteria["correctness"]["score_a"] == 2 and n.criteria["correctness"]["score_b"] == 4
    assert n.raw_score["winner"] == "A"  # the raw judge JSON is preserved untouched


def test_tie_survives_swapping():
    assert norm(verdict_json(3, 3), swapped=True).winner == "TIE"


def test_weighted_score_uses_rubric_weights_not_judge_overall():
    d = verdict_dict(3, 3)
    d["criteria"]["correctness"].update(score_a=5, score_b=1)  # weight 2.0
    d["criteria"]["clarity"].update(score_a=1, score_b=5)  # weight 1.0
    d["winner"], d["overall_score_a"], d["overall_score_b"] = (
        "A",
        1,
        1,
    )  # judge's own overall is ignored
    n = norm(json.dumps(d), swapped=False)
    assert n.score_a == pytest.approx((5 * 2 + 3 + 3 + 1) / 5)
    assert n.score_b == pytest.approx((1 * 2 + 3 + 3 + 5) / 5)


def test_combine_consistent_passes():
    c = combine_passes(
        [
            norm(verdict_json(4, 2, confidence=0.8), False, 0),
            norm(verdict_json(2, 4, confidence=0.6), True, 1),
        ]
    )
    assert c.winner == "A" and c.position_consistent is True
    assert c.confidence == pytest.approx(0.7)
    assert c.score_a == pytest.approx(4) and c.score_b == pytest.approx(2)


def test_combine_contradictory_passes_is_a_tie_with_reduced_confidence():
    """A judge that always answers 'A' is position-biased: it picks A, then B after swapping."""
    c = combine_passes(
        [
            norm(verdict_json(5, 1, confidence=0.9), False, 0),
            norm(verdict_json(5, 1, confidence=0.9), True, 1),
        ]
    )
    assert c.winner == "TIE" and c.position_consistent is False
    assert c.confidence == pytest.approx(0.0)  # no pass agrees with TIE


def test_combine_decisive_plus_tie_keeps_decisive_winner_with_half_agreement():
    c = combine_passes(
        [
            norm(verdict_json(4, 2, confidence=0.8), False, 0),
            norm(verdict_json(3, 3, confidence=0.6), True, 1),
        ]
    )
    assert c.winner == "A" and c.position_consistent is True
    assert c.confidence == pytest.approx(0.7 * 0.5)


def test_single_pass_combination():
    c = combine_passes([norm(verdict_json(1, 5, confidence=0.5), False)])
    assert c.winner == "B" and c.confidence == 0.5


def test_plan_passes():
    assert plan_passes("both", "x") == [False, True]
    assert plan_passes("none", "x") == [False]
    flags = {plan_passes("alternate", f"run:{i}")[0] for i in range(40)}
    assert flags == {True, False}  # about half the cases are swapped
    assert plan_passes("alternate", "run:1") == plan_passes("alternate", "run:1")  # deterministic


# ---- end-to-end judge call --------------------------------------------------------------------
async def judge(handler, **kw):
    provider = ScriptedProvider(handler)
    cfg = JudgeConfig(provider="mock", model="m", max_attempts=kw.pop("max_attempts", 3))

    async def nosleep(_):
        return None

    result = None
    try:
        result = await run_judge_pass(
            provider=provider,
            gate=ProviderGate(2),
            rubric=RUBRIC,
            config=cfg,
            input_text="q",
            expected_behavior={},
            output_a="A-text",
            output_b="B-text",
            prompt_a="pa",
            prompt_b="pb",
            swapped=kw.pop("swapped", False),
            pass_index=0,
            timeout=5,
            max_retries=2,
            backoff_base=0,
            sleep=nosleep,
        )
    finally:
        judge.provider = provider
    return result


async def test_judge_pass_success_uses_json_mode_and_system_prompt():
    n = await judge(lambda *a: verdict_json(4, 2))
    call = judge.provider.calls[0]
    assert call["system"] == JUDGE_SYSTEM_PROMPT and call["params"].json_mode is True
    assert call["params"].temperature == 0.0
    assert (
        n.winner == "A"
        and n.attempts == 1
        and n.prompt_tokens == 10
        and n.estimated_cost == pytest.approx(0.001)
    )


async def test_judge_pass_presents_swapped_outputs_in_swapped_order():
    await judge(lambda *a: verdict_json(3, 3), swapped=True)
    prompt = judge.provider.calls[0]["prompt"]
    assert prompt.index("Response A:\n<<<\nB-text") < prompt.index("Response B:\n<<<\nA-text")


async def test_malformed_judge_output_is_retried_with_feedback_then_succeeds():
    replies = iter(
        ["I think A is better", json.dumps(verdict_dict(confidence=2)), verdict_json(4, 2)]
    )
    n = await judge(lambda *a: next(replies))
    assert n.attempts == 3 and len(judge.provider.calls) == 3
    assert "previous reply was rejected" in judge.provider.calls[1]["prompt"]
    assert "confidence" in judge.provider.calls[2]["prompt"]
    assert n.prompt_tokens == 30  # tokens of all attempts are accounted for


async def test_judge_gives_up_instead_of_inventing_a_score():
    with pytest.raises(JudgeError) as exc:
        await judge(lambda *a: "totally not json", max_attempts=2)
    assert exc.value.kind == "invalid_output" and exc.value.attempts == 2
    assert exc.value.raw_response == "totally not json" and len(judge.provider.calls) == 2
    assert exc.value.usage["prompt_tokens"] == 20


async def test_judge_provider_failure_is_reported():
    with pytest.raises(JudgeError) as exc:
        await judge(lambda *a: http_error(401))
    assert exc.value.kind == "client_error"
