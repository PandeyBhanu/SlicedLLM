import asyncio
import uuid

import pytest
from sqlalchemy import func, select

from app.audit import verify_audit_chain
from app.core.config import settings
from app.jobs.worker import JobWorker
from app.models.evaluation import CandidateOutput, JudgeEvaluation, RubricScore
from tests.helpers import (
    DEFAULT_CRITERIA,
    ScriptedProvider,
    builder_for,
    create_dataset_with_cases,
    create_prompt_with_versions,
    honest_handler,
    http_error,
    start_run,
    verdict_json,
)

EVAL = "/api/v1/evaluations"


@pytest.fixture(autouse=True)
def fast_backoff(monkeypatch):
    monkeypatch.setattr(settings, "EVALUATION_BACKOFF_BASE", 0.001)


@pytest.fixture
async def env(client):
    prompt_id, (good, bad) = await create_prompt_with_versions(client)
    ds = await create_dataset_with_cases(client, n=3)
    return {"prompt": prompt_id, "good": good, "bad": bad, "ds": ds}


def make_worker(session_factory, provider, **kw):
    return JobWorker(
        session_factory,
        builder_for(provider),
        worker_id=kw.pop("worker_id", "test-worker"),
        heartbeat_interval=kw.pop("heartbeat_interval", 0.05),
        poll_interval=0.01,
        **kw,
    )


async def run_to_end(
    client, session_factory, provider, env, *, a="good", b="bad", settings_=None, **extra
):
    run = await start_run(client, env["ds"], env[a], env[b], settings=settings_ or {}, **extra)
    worker = make_worker(session_factory, provider)
    assert await worker.run_once() is True
    return (await client.get(f"{EVAL}/runs/{run['id']}")).json(), run["id"]


async def test_full_run_persists_outputs_judgements_and_scores(client, session_factory, env):
    provider = ScriptedProvider(honest_handler())
    run, run_id = await run_to_end(client, session_factory, provider, env)
    assert run["status"] == "COMPLETED" and run["error"] is None
    assert run["progress"] == {"total_cases": 3, "completed_cases": 3, "failed_cases": 0}
    assert run["version_a_label"] == "1.0.0" and run["version_b_label"] == "1.1.0"
    assert run["provider"] == "ollama" and run["model"] == "m" and run["judge_model"] == "m"
    assert run["config"]["judge_position_strategy"] == "both" and run["attempts"] == 1

    cases = (await client.get(f"{EVAL}/runs/{run_id}/cases")).json()
    assert [c["ordinal"] for c in cases] == [0, 1, 2]
    for i, case in enumerate(cases):
        assert case["input_text"] == f"question {i}" and case["status"] == "COMPLETED"
        assert case["winner"] == "A" and case["position_consistent"] is True
        assert case["score_a"] == pytest.approx(5) and case["score_b"] == pytest.approx(2)
        assert case["confidence"] == pytest.approx(
            0.8
        )  # the judge's own confidence, not a constant

        out_a, out_b = case["outputs"]
        assert (out_a["slot"], out_b["slot"]) == ("A", "B")
        assert (
            out_a["prompt_version_id"] == env["good"] and out_b["prompt_version_id"] == env["bad"]
        )
        assert out_a["rendered_prompt"] == f"Answer well: question {i}"
        assert out_b["rendered_prompt"] == f"Answer badly: question {i}"
        assert "QUALITY=5" in out_a["output_text"] and "QUALITY=2" in out_b["output_text"]
        assert out_a["generation_params"]["temperature"] == 0.2
        assert (out_a["provider"], out_a["model"]) == ("ollama", "m")
        assert (out_a["prompt_tokens"], out_a["completion_tokens"], out_a["total_tokens"]) == (
            10,
            20,
            30,
        )
        assert out_a["estimated_cost"] == pytest.approx(0.001) and out_a[
            "latency_ms"
        ] == pytest.approx(12.5)
        assert out_a["started_at"] <= out_a["completed_at"]

        judges = case["judge_evaluations"]
        assert [(j["pass_index"], j["swapped"]) for j in judges] == [(0, False), (1, True)]
        for j in judges:
            assert j["status"] == "COMPLETED" and j["winner"] == "A" and j["rubric_version"] == 1
            assert (j["judge_provider"], j["judge_model"]) == ("ollama", "m")
            assert j["confidence"] == pytest.approx(0.8) and j["reasoning"] == "because"
            assert j["normalized_score_a"] == pytest.approx(1.0) and j[
                "normalized_score_b"
            ] == pytest.approx(0.25)
            assert j["raw_score"]["criteria"]["correctness"]["reason"] == "correctness reason"
            assert {s["criterion"] for s in j["rubric_scores"]} == set(DEFAULT_CRITERIA)
            assert all(s["score_a"] == 5 and s["score_b"] == 2 for s in j["rubric_scores"])
            # the swapped pass stored raw judge positions (good answer sat in position B)
        # but normalised winner A
        assert judges[1]["raw_score"]["winner"] == "B"

    async with session_factory() as s:
        assert (await s.scalar(select(func.count()).select_from(CandidateOutput))) == 6
        assert (await s.scalar(select(func.count()).select_from(JudgeEvaluation))) == 6
        assert (await s.scalar(select(func.count()).select_from(RubricScore))) == 24

    assert provider.closed is True
    assert len(provider.candidate_calls) == 6 and len(provider.judge_calls) == 6


async def test_swapped_pass_really_shows_the_judge_the_outputs_in_the_other_order(
    client, session_factory, env
):
    provider = ScriptedProvider(honest_handler())
    await run_to_end(client, session_factory, provider, env, settings_={"case_concurrency": 1})
    first_case = [c["prompt"] for c in provider.judge_calls][:2]
    plain = next(p for p in first_case if p.index("QUALITY=5") < p.index("QUALITY=2"))
    swapped = next(p for p in first_case if p.index("QUALITY=2") < p.index("QUALITY=5"))
    assert plain != swapped


async def test_reversed_versions_flip_the_winner(client, session_factory, env):
    run, run_id = await run_to_end(
        client, session_factory, ScriptedProvider(honest_handler()), env, a="bad", b="good"
    )
    assert run["status"] == "COMPLETED"
    summary = (await client.get(f"{EVAL}/runs/{run_id}/summary")).json()
    assert (summary["wins_a"], summary["wins_b"], summary["ties"]) == (0, 3, 0)


async def test_a_and_b_generation_run_concurrently(client, session_factory, env):
    provider = ScriptedProvider(honest_handler(), delay=0.05)
    await run_to_end(client, session_factory, provider, env, settings_={"case_concurrency": 1})
    assert provider.max_inflight == 2  # exactly A and B of a single case overlapped


async def test_ab_overlap_is_observable_in_timestamps(client, session_factory, env):
    provider = ScriptedProvider(honest_handler(), delay=0.1)
    _, run_id = await run_to_end(
        client, session_factory, provider, env, settings_={"case_concurrency": 1}
    )
    case = (await client.get(f"{EVAL}/runs/{run_id}/cases")).json()[0]
    a, b = case["outputs"]
    # sequential execution would need b.started_at >= a.completed_at
    assert b["started_at"] < a["completed_at"] and a["started_at"] < b["completed_at"]


async def test_inflight_requests_are_capped_and_tasks_are_bounded(client, session_factory):
    prompt_id, (good, bad) = await create_prompt_with_versions(client)
    ds = await create_dataset_with_cases(client, n=30)
    env = {"good": good, "bad": bad, "ds": ds}
    task_counts = []
    inner = honest_handler()

    def handler(prompt, system, params):
        task_counts.append(len(asyncio.all_tasks()))
        return inner(prompt, system, params)

    provider = ScriptedProvider(handler, delay=0.01)
    run, _ = await run_to_end(
        client,
        session_factory,
        provider,
        env,
        settings_={"case_concurrency": 4, "max_inflight_requests": 3},
    )
    assert run["status"] == "COMPLETED" and run["progress"]["completed_cases"] == 30
    assert provider.max_inflight == 3
    assert max(task_counts) < 30, f"task count grew with dataset size: {max(task_counts)}"


async def test_partial_candidate_failure_keeps_the_rest_of_the_run(client, session_factory, env):
    inner = honest_handler()

    def handler(prompt, system, params):
        if system is None and "question 1" in prompt and "well" in prompt:
            return http_error(400)
        return inner(prompt, system, params)

    run, run_id = await run_to_end(client, session_factory, ScriptedProvider(handler), env)
    assert run["status"] == "COMPLETED" and run["error"] == "1 of 3 cases failed"
    assert run["progress"] == {"total_cases": 3, "completed_cases": 2, "failed_cases": 1}
    cases = (await client.get(f"{EVAL}/runs/{run_id}/cases")).json()
    bad = cases[1]
    assert (
        bad["status"] == "FAILED" and "candidate A failed" in bad["error"] and bad["winner"] is None
    )
    assert bad["confidence"] is None and bad["judge_evaluations"] == []
    statuses = {o["slot"]: o["status"] for o in bad["outputs"]}
    assert statuses == {"A": "FAILED", "B": "COMPLETED"}  # the surviving output is not lost
    assert "QUALITY=2" in next(o for o in bad["outputs"] if o["slot"] == "B")["output_text"]
    summary = (await client.get(f"{EVAL}/runs/{run_id}/summary")).json()
    assert summary["failed_cases"] == 1 and summary["slot_a"]["outputs_failed"] == 1


async def test_run_fails_when_every_case_fails(client, session_factory, env):
    run, _ = await run_to_end(
        client, session_factory, ScriptedProvider(lambda *a: http_error(401)), env
    )
    assert run["status"] == "FAILED" and run["error"].startswith("No case completed")


async def test_malformed_judge_output_marks_case_failed_without_inventing_scores(
    client, session_factory, env
):
    provider = ScriptedProvider(honest_handler(judge_override=lambda prompt: "I like A."))
    run, run_id = await run_to_end(client, session_factory, provider, env)
    assert run["status"] == "FAILED"
    cases = (await client.get(f"{EVAL}/runs/{run_id}/cases")).json()
    for case in cases:
        assert case["status"] == "FAILED" and "judge failed" in case["error"]
        assert case["winner"] is None and case["score_a"] is None and case["confidence"] is None
        assert len(case["outputs"]) == 2  # candidate outputs are still stored
        for j in case["judge_evaluations"]:
            assert (
                j["status"] == "FAILED"
                and j["attempts"] == 3
                and j["winner"] is None
                and j["rubric_scores"] == []
            )
    assert len(provider.judge_calls) == 3 * 2 * 3  # cases x passes x attempts


async def test_judge_retries_invalid_output_and_then_succeeds(client, session_factory, env):
    replies = {}

    def judge_override(prompt):
        replies[prompt] = replies.get(prompt, 0) + 1
        return "oops" if "rejected" not in prompt else verdict_json(5, 2)

    provider = ScriptedProvider(honest_handler(judge_override=judge_override))
    run, run_id = await run_to_end(
        client, session_factory, provider, env, settings_={"judge_position_strategy": "none"}
    )
    assert run["status"] == "COMPLETED"
    cases = (await client.get(f"{EVAL}/runs/{run_id}/cases")).json()
    assert all(
        len(c["judge_evaluations"]) == 1 and c["judge_evaluations"][0]["attempts"] == 2
        for c in cases
    )


async def test_candidate_429_is_retried_and_recorded(client, session_factory, env):
    inner = honest_handler()
    state = {"n": 0}

    def handler(prompt, system, params):
        if system is None:
            state["n"] += 1
            if state["n"] <= 2:
                return http_error(429, retry_after="0")
        return inner(prompt, system, params)

    run, run_id = await run_to_end(client, session_factory, ScriptedProvider(handler), env)
    assert run["status"] == "COMPLETED" and run["progress"]["failed_cases"] == 0
    cases = (await client.get(f"{EVAL}/runs/{run_id}/cases")).json()
    assert max(o["attempts"] for c in cases for o in c["outputs"]) == 2


async def test_persistent_5xx_fails_the_case_after_retries(client, session_factory, env):
    inner = honest_handler()
    calls = {"n": 0}

    def handler(prompt, system, params):
        if system is None and "question 0" in prompt and "badly" in prompt:
            calls["n"] += 1
            return http_error(503)
        return inner(prompt, system, params)

    run, run_id = await run_to_end(
        client, session_factory, ScriptedProvider(handler), env, settings_={"max_retries": 2}
    )
    assert run["status"] == "COMPLETED" and run["progress"]["failed_cases"] == 1
    assert calls["n"] == 3  # 1 try + 2 retries
    case = (await client.get(f"{EVAL}/runs/{run_id}/cases")).json()[0]
    assert case["status"] == "FAILED" and "server_error" in case["error"]
    assert next(o for o in case["outputs"] if o["slot"] == "B")["attempts"] == 3


async def test_candidate_timeout_is_reported(client, session_factory, env):
    inner = honest_handler()

    async def handler(prompt, system, params):
        if system is None and "question 2" in prompt and "well" in prompt:
            await asyncio.sleep(5)
        return inner(prompt, system, params)

    run, run_id = await run_to_end(
        client,
        session_factory,
        ScriptedProvider(handler),
        env,
        settings_={"call_timeout_s": 0.05, "max_retries": 0},
    )
    assert run["progress"]["failed_cases"] == 1
    case = (await client.get(f"{EVAL}/runs/{run_id}/cases")).json()[2]
    assert case["status"] == "FAILED" and "timeout" in case["error"]


async def test_undefined_template_variable_fails_the_case_clearly(client, session_factory):
    prompt_id, (a, b) = await create_prompt_with_versions(
        client, templates=[("1.0.0", "Hi {{input}} {{who}}"), ("1.1.0", "Hi {{input}}")]
    )
    ds = await create_dataset_with_cases(client, n=1)
    run, run_id = await run_to_end(
        client,
        session_factory,
        ScriptedProvider(honest_handler()),
        {"a": a, "b": b, "ds": ds},
        a="a",
        b="b",
    )
    case = (await client.get(f"{EVAL}/runs/{run_id}/cases")).json()[0]
    assert run["status"] == "FAILED" and "undefined variable(s): who" in case["error"]


async def test_summary_aggregates_only_persisted_data(client, session_factory, env):
    def cand(prompt, system, params):
        if "question 2" in prompt:
            return "answer QUALITY=4"
        good = "well" in prompt
        flip = "question 1" in prompt
        return f"answer QUALITY={5 if good != flip else 2}"

    inner = honest_handler()

    def handler(prompt, system, params):
        return inner(prompt, system, params) if system else cand(prompt, system, params)

    _, run_id = await run_to_end(client, session_factory, ScriptedProvider(handler), env)
    s = (await client.get(f"{EVAL}/runs/{run_id}/summary")).json()
    assert (s["wins_a"], s["wins_b"], s["ties"]) == (1, 1, 1)
    assert s["win_rate_a"] == pytest.approx(1 / 3) and s["tie_rate"] == pytest.approx(1 / 3)
    assert s["a_share_of_decisive"] == pytest.approx(0.5)
    assert 0 < s["a_share_ci_low"] < 0.5 < s["a_share_ci_high"] < 1
    assert s["avg_confidence"] == pytest.approx(0.8) and s["position_consistency_rate"] == 1.0
    assert s["slot_a"]["prompt_tokens"] == 30 and s["slot_a"]["total_tokens"] == 90
    assert s["slot_a"]["avg_latency_ms"] == pytest.approx(12.5)
    assert s["slot_a"]["estimated_cost"] == pytest.approx(0.003)
    assert s["judge_tokens"] == 6 * 30 and s["judge_cost"] == pytest.approx(0.006)
    assert s["total_cost"] == pytest.approx(0.003 * 2 + 0.006)
    assert {c["criterion"] for c in s["criteria"]} == set(DEFAULT_CRITERIA)
    assert all(c["samples"] == 6 for c in s["criteria"])
    assert s["rubric_scale_min"] == 1 and s["rubric_scale_max"] == 5


async def test_custom_rubric_is_versioned_and_used_by_the_judge(client, session_factory, env):
    body = {"name": "tiny", "criteria": [{"name": "accuracy", "weight": 3}, {"name": "tone"}]}
    r1 = (await client.post(f"{EVAL}/rubrics", json=body)).json()
    r2 = (await client.post(f"{EVAL}/rubrics", json=body)).json()
    assert (r1["version"], r2["version"]) == (1, 2) and r1["definition_hash"] != r2[
        "definition_hash"
    ]
    assert (
        await client.post(
            f"{EVAL}/rubrics", json={"name": "x", "criteria": [{"name": "a"}, {"name": "a"}]}
        )
    ).status_code == 400

    inner = honest_handler()

    def handler(prompt, system, params):
        if system:
            return verdict_json(4, 1, criteria=["accuracy", "tone"])
        return inner(prompt, system, params)

    _, run_id = await run_to_end(
        client, session_factory, ScriptedProvider(handler), env, rubric_id=r2["id"]
    )
    case = (await client.get(f"{EVAL}/runs/{run_id}/cases")).json()[0]
    assert {s["criterion"] for s in case["judge_evaluations"][0]["rubric_scores"]} == {
        "accuracy",
        "tone",
    }
    assert case["judge_evaluations"][0]["rubric_version"] == 2
    listing = (await client.get(f"{EVAL}/rubrics")).json()
    assert {r["name"] for r in listing} == {"tiny", "general-quality"}


async def test_judge_can_be_a_different_provider_and_model(client, session_factory, env):
    cand, judge_p = (
        ScriptedProvider(honest_handler(), model="cand"),
        ScriptedProvider(honest_handler(), name="groq", model="judge"),
    )

    def builder(provider, model):
        return judge_p if (provider, model) == ("groq", "big-judge") else cand

    worker = JobWorker(
        session_factory, builder, worker_id="w", heartbeat_interval=0.05, poll_interval=0.01
    )
    run = await start_run(
        client, env["ds"], env["good"], env["bad"], judge_provider="groq", judge_model="big-judge"
    )
    await worker.run_once()
    final = (await client.get(f"{EVAL}/runs/{run['id']}")).json()
    assert final["status"] == "COMPLETED" and (final["judge_provider"], final["judge_model"]) == (
        "groq",
        "big-judge",
    )
    assert len(cand.judge_calls) == 0 and len(judge_p.candidate_calls) == 0
    assert len(cand.candidate_calls) == 6 and len(judge_p.judge_calls) == 6
    assert cand.closed and judge_p.closed
    case = (await client.get(f"{EVAL}/runs/{run['id']}/cases")).json()[0]
    assert (
        case["judge_evaluations"][0]["judge_model"] == "big-judge"
        and case["outputs"][0]["model"] == "m"
    )


async def test_single_position_strategies(client, session_factory, env):
    provider = ScriptedProvider(honest_handler())
    _, run_id = await run_to_end(
        client, session_factory, provider, env, settings_={"judge_position_strategy": "alternate"}
    )
    cases = (await client.get(f"{EVAL}/runs/{run_id}/cases")).json()
    assert all(len(c["judge_evaluations"]) == 1 for c in cases)
    assert len(provider.judge_calls) == 3


async def test_biased_judge_that_always_prefers_position_a_is_neutralised(
    client, session_factory, env
):
    provider = ScriptedProvider(
        honest_handler(judge_override=lambda prompt: verdict_json(5, 1, winner="A"))
    )
    run, run_id = await run_to_end(client, session_factory, provider, env)
    cases = (await client.get(f"{EVAL}/runs/{run_id}/cases")).json()
    assert all(c["winner"] == "TIE" and c["position_consistent"] is False for c in cases)
    assert all(c["confidence"] == pytest.approx(0.0) for c in cases)
    summary = (await client.get(f"{EVAL}/runs/{run_id}/summary")).json()
    assert summary["ties"] == 3 and summary["position_consistency_rate"] == 0.0


async def test_run_config_and_defaults_are_recorded(client, session_factory, env):
    run = await start_run(
        client,
        env["ds"],
        env["good"],
        env["bad"],
        settings={"case_concurrency": 2, "max_retries": 1, "judge_position_strategy": "none"},
    )
    assert run["status"] == "PENDING" and run["total_cases"] == 3
    assert run["config"]["case_concurrency"] == 2 and run["config"]["max_retries"] == 1
    assert run["config"]["call_timeout_s"] == settings.EVALUATION_CALL_TIMEOUT
    assert (
        run["judge_provider"] == "ollama" and run["judge_model"] == "m"
    )  # defaults to the candidate model


async def test_run_creation_validation(client, env):
    base = {
        "dataset_id": env["ds"],
        "prompt_version_a_id": env["good"],
        "prompt_version_b_id": env["bad"],
        "provider": "ollama",
        "model": "m",
    }
    assert (await client.post(f"{EVAL}/runs", json={**base, "provider": "nope"})).status_code == 400
    assert (
        await client.post(f"{EVAL}/runs", json={**base, "judge_provider": "nope"})
    ).status_code == 400
    assert (
        await client.post(f"{EVAL}/runs", json={**base, "prompt_version_b_id": str(uuid.uuid4())})
    ).status_code == 404
    assert (
        await client.post(f"{EVAL}/runs", json={**base, "rubric_id": str(uuid.uuid4())})
    ).status_code == 404
    assert (
        await client.post(f"{EVAL}/runs", json={**base, "dataset_id": str(uuid.uuid4())})
    ).status_code == 404
    body = dict(base)
    del body["prompt_version_b_id"]
    assert (await client.post(f"{EVAL}/runs", json=body)).status_code == 422
    empty = (await client.post("/api/v1/datasets", json={"name": "empty"})).json()["id"]
    assert (
        await client.post(f"{EVAL}/runs", json={**base, "dataset_id": empty})
    ).status_code == 400
    assert (
        await client.post(f"{EVAL}/runs", json={**base, "settings": {"case_concurrency": 0}})
    ).status_code == 422
    assert (await client.get(f"{EVAL}/runs/{uuid.uuid4()}")).status_code == 404


async def test_list_runs_and_datasets_endpoints(client, session_factory, env):
    run = await start_run(client, env["ds"], env["good"], env["bad"])
    runs = (await client.get(f"{EVAL}/runs")).json()
    assert [r["id"] for r in runs] == [run["id"]] and runs[0]["dataset_name"] == "ds1"
    datasets = (await client.get("/api/v1/datasets")).json()
    assert datasets[0]["case_count"] == 3
    detail = (await client.get(f"/api/v1/datasets/{env['ds']}")).json()
    assert [c["ordinal"] for c in detail["cases"]] == [0, 1, 2]


async def test_cancel_pending_run(client, session_factory, env):
    run = await start_run(client, env["ds"], env["good"], env["bad"])
    cancelled = (await client.post(f"{EVAL}/runs/{run['id']}/cancel")).json()
    assert cancelled["status"] == "CANCELLED" and cancelled["completed_at"]
    assert (
        await make_worker(session_factory, ScriptedProvider(honest_handler())).run_once() is False
    )
    assert (await client.post(f"{EVAL}/runs/{run['id']}/cancel")).status_code == 400


async def test_cancel_running_run_stops_work_and_keeps_finished_cases(client, session_factory, env):
    release = asyncio.Event()
    inner = honest_handler()

    async def handler(prompt, system, params):
        if system is None and "question 1" in prompt:
            await release.wait()  # blocks forever: simulates a slow provider
        return inner(prompt, system, params)

    provider = ScriptedProvider(handler)
    run = await start_run(
        client, env["ds"], env["good"], env["bad"], settings={"case_concurrency": 1}
    )
    task = asyncio.create_task(make_worker(session_factory, provider).run_once())
    for _ in range(400):
        if any("question 1" in c["prompt"] for c in provider.calls):
            break
        await asyncio.sleep(0.01)
    assert (await client.get(f"{EVAL}/runs/{run['id']}")).json()["status"] == "RUNNING"
    resp = await client.post(f"{EVAL}/runs/{run['id']}/cancel")
    assert resp.status_code == 200 and resp.json()["cancel_requested"] is True
    assert await asyncio.wait_for(task, timeout=10) is True
    final = (await client.get(f"{EVAL}/runs/{run['id']}")).json()
    assert final["status"] == "CANCELLED" and final["progress"]["completed_cases"] == 1
    assert provider.inflight == 0


async def test_run_and_cancel_are_audited_and_chain_stays_valid(client, session_factory, env, db):
    run = await start_run(client, env["ds"], env["good"], env["bad"])
    await client.post(f"{EVAL}/runs/{run['id']}/cancel")
    events = (
        await client.get("/api/v1/audit/events", params={"entity_type": "EvaluationRun"})
    ).json()
    assert [e["action"] for e in reversed(events)] == ["CREATE", "CANCEL"]
    assert events[-1]["after_state"]["config"]["judge_position_strategy"] == "both"
    assert (await verify_audit_chain(db)).valid
