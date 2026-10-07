import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError

from app.jobs.queue import claim_next_run, heartbeat, recover_interrupted, utcnow
from app.jobs.worker import JobWorker
from app.models.evaluation import EvaluationResult, EvaluationRun
from tests.helpers import (
    ScriptedProvider,
    builder_for,
    create_dataset_with_cases,
    create_prompt_with_versions,
    honest_handler,
    start_run,
)

EVAL = "/api/v1/evaluations"


async def make_runs(client, n_runs=1, n_cases=3):
    prompt_id, (good, bad) = await create_prompt_with_versions(client)
    ds = await create_dataset_with_cases(client, n=n_cases)
    return [await start_run(client, ds, good, bad) for _ in range(n_runs)]


def worker(session_factory, provider, worker_id="w1", **kw):
    return JobWorker(
        session_factory,
        builder_for(provider),
        worker_id=worker_id,
        heartbeat_interval=kw.pop("heartbeat_interval", 0.05),
        poll_interval=0.01,
        **kw,
    )


async def test_concurrent_workers_never_claim_the_same_run(client, session_factory):
    await make_runs(client, n_runs=6)

    async def claim(i):
        async with session_factory() as s:
            return await claim_next_run(s, f"w{i}")

    claimed = await asyncio.gather(*(claim(i) for i in range(6)))
    assert len({c for c in claimed if c}) == 6 and None not in claimed
    async with session_factory() as s:
        assert await claim_next_run(s, "late") is None
        rows = (await s.execute(select(EvaluationRun))).scalars().all()
    assert {r.status for r in rows} == {"RUNNING"} and {r.attempts for r in rows} == {1}


async def test_worker_marks_status_transitions(client, session_factory):
    (run,) = await make_runs(client)
    seen = []
    inner = honest_handler()

    def handler(prompt, system, params):
        return inner(prompt, system, params)

    w = worker(session_factory, ScriptedProvider(handler, delay=0.02))
    task = asyncio.create_task(w.run_once())
    for _ in range(200):
        status = (await client.get(f"{EVAL}/runs/{run['id']}")).json()["status"]
        if not seen or seen[-1] != status:
            seen.append(status)
        if status == "COMPLETED":
            break
        await asyncio.sleep(0.01)
    await task
    assert seen[0] in ("PENDING", "RUNNING") and seen[-1] == "COMPLETED" and "RUNNING" in seen
    final = (await client.get(f"{EVAL}/runs/{run['id']}")).json()
    assert final["started_at"] and final["completed_at"] and final["attempts"] == 1


async def test_heartbeat_updates_and_reports_cancel(client, session_factory):
    (run,) = await make_runs(client)
    async with session_factory() as s:
        rid = await claim_next_run(s, "w1")
    async with session_factory() as s:
        assert await heartbeat(s, rid, "w1") == (True, False)
        assert await heartbeat(s, rid, "someone-else") == (False, False)
    await client.post(f"{EVAL}/runs/{run['id']}/cancel")
    async with session_factory() as s:
        assert await heartbeat(s, rid, "w1") == (True, True)


async def test_recovery_requeues_runs_whose_worker_stopped_heartbeating(client, session_factory):
    (run,) = await make_runs(client)
    async with session_factory() as s:
        rid = await claim_next_run(s, "dead-worker")
        await s.execute(
            update(EvaluationRun)
            .where(EvaluationRun.id == rid)
            .values(heartbeat_at=utcnow() - timedelta(minutes=5))
        )
        await s.commit()
    async with session_factory() as s:
        assert await recover_interrupted(s, stale_after_s=60, max_attempts=3) == [(rid, "PENDING")]
    final = (await client.get(f"{EVAL}/runs/{run['id']}")).json()
    assert final["status"] == "PENDING" and final["attempts"] == 1


async def test_recovery_ignores_runs_with_a_fresh_heartbeat(client, session_factory):
    await make_runs(client)
    async with session_factory() as s:
        await claim_next_run(s, "alive")
    async with session_factory() as s:
        assert await recover_interrupted(s, stale_after_s=60, max_attempts=3) == []


async def test_recovery_gives_up_after_max_attempts(client, session_factory):
    (run,) = await make_runs(client)
    for _ in range(3):
        async with session_factory() as s:
            await claim_next_run(s, "w")
        async with session_factory() as s:
            changes = await recover_interrupted(s, stale_after_s=0, max_attempts=3)
    assert changes[0][1] == "FAILED"
    final = (await client.get(f"{EVAL}/runs/{run['id']}")).json()
    assert (
        final["status"] == "FAILED"
        and "Interrupted 3 times" in final["error"]
        and final["completed_at"]
    )


async def test_recovery_finishes_cancellation_of_a_dead_runs_with_cancel_requested(
    client, session_factory
):
    (run,) = await make_runs(client)
    async with session_factory() as s:
        await claim_next_run(s, "w")
    await client.post(f"{EVAL}/runs/{run['id']}/cancel")
    async with session_factory() as s:
        await recover_interrupted(s, stale_after_s=0, max_attempts=3)
    assert (await client.get(f"{EVAL}/runs/{run['id']}")).json()["status"] == "CANCELLED"


async def test_startup_recovery_skips_its_own_runs(client, session_factory):
    await make_runs(client)
    async with session_factory() as s:
        await claim_next_run(s, "me")
    async with session_factory() as s:
        assert (
            await recover_interrupted(s, stale_after_s=0, max_attempts=3, exclude_worker="me") == []
        )


async def test_crashed_run_resumes_without_redoing_finished_cases(client, session_factory):
    """Kill the worker mid-run (as a process crash/deploy would), restart, and finish the run."""
    (run,) = await make_runs(client, n_cases=4)
    inner = honest_handler()
    gate_second_case = asyncio.Event()

    async def handler(prompt, system, params):
        if system is None and "question 2" in prompt:
            await gate_second_case.wait()  # worker is "killed" while stuck here
        return inner(prompt, system, params)

    first = ScriptedProvider(handler)
    w1 = worker(session_factory, first, worker_id="w1")
    task = asyncio.create_task(w1.run_once())
    # run is configured with default case_concurrency=4, so cases 0,1,3 finish while case 2 hangs
    for _ in range(500):
        async with session_factory() as s:
            done = len((await s.execute(select(EvaluationResult))).scalars().all())
        if done == 3:
            break
        await asyncio.sleep(0.01)
    assert done == 3
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    crashed = (await client.get(f"{EVAL}/runs/{run['id']}")).json()
    assert crashed["status"] == "RUNNING"  # nobody marked it: exactly the "stuck forever" situation

    second = ScriptedProvider(honest_handler())
    w2 = worker(session_factory, second, worker_id="w2")
    await w2.recover_on_startup()
    assert (await client.get(f"{EVAL}/runs/{run['id']}")).json()["status"] == "PENDING"
    assert await w2.run_once() is True

    final = (await client.get(f"{EVAL}/runs/{run['id']}")).json()
    assert final["status"] == "COMPLETED" and final["attempts"] == 2
    assert final["progress"]["completed_cases"] == 4
    regenerated = {c["prompt"] for c in second.candidate_calls}
    assert len(second.candidate_calls) == 2 and all("question 2" in p for p in regenerated)
    cases = (await client.get(f"{EVAL}/runs/{run['id']}/cases")).json()
    assert [c["ordinal"] for c in cases] == [0, 1, 2, 3] and all(
        c["status"] == "COMPLETED" for c in cases
    )


async def test_worker_loop_picks_up_runs_and_stops_cleanly(client, session_factory):
    w = worker(session_factory, ScriptedProvider(honest_handler()))
    loop_task = asyncio.create_task(w.run_forever())
    (run,) = await make_runs(client)
    for _ in range(500):
        if (await client.get(f"{EVAL}/runs/{run['id']}")).json()["status"] == "COMPLETED":
            break
        await asyncio.sleep(0.02)
    else:
        pytest.fail("worker did not complete the run")
    w.stop()
    await asyncio.wait_for(loop_task, timeout=5)


async def test_unexpected_executor_error_fails_the_run_instead_of_hanging(client, session_factory):
    (run,) = await make_runs(client)

    def exploding_builder(provider, model):
        raise RuntimeError("cannot build provider")

    w = JobWorker(
        session_factory,
        exploding_builder,
        worker_id="w",
        heartbeat_interval=0.05,
        poll_interval=0.01,
    )
    await w.run_once()
    final = (await client.get(f"{EVAL}/runs/{run['id']}")).json()
    assert final["status"] == "FAILED" and "cannot build provider" in final["error"]


async def test_duplicate_result_insert_is_ignored(client, session_factory):
    """If two attempts race on the same case, the unique (run, case) constraint keeps
    the first result."""
    (run,) = await make_runs(client, n_cases=1)
    await worker(session_factory, ScriptedProvider(honest_handler())).run_once()
    async with session_factory() as s:
        before = (await s.execute(select(EvaluationResult))).scalars().all()
        assert len(before) == 1
        with pytest.raises(IntegrityError):
            await s.execute(
                text(
                    "INSERT INTO evaluation_results (id, evaluation_run_id, "
                    "evaluation_case_id, status) SELECT gen_random_uuid(), evaluation_run_id, "
                    "evaluation_case_id, 'FAILED' FROM evaluation_results"
                )
            )
            await s.commit()
