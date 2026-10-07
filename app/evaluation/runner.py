"""Executes one evaluation run end to end.

Per case:   render A and B prompts -> generate A and B CONCURRENTLY -> judge the two outputs
            (1 or 2 presentation orders, concurrently) -> persist everything in one transaction.

Concurrency model (no unbounded task creation):
  * `case_concurrency` worker tasks pull cases from an asyncio.Queue;
  * each case spawns at most 2 generation tasks, then at most 2 judge tasks;
  * all LLM requests additionally pass through one `ProviderGate` (in-flight cap, rate limit,
    shared 429 cool-down).
So live tasks <= case_concurrency * 2 + 2 (heartbeat + cancel watcher), regardless of dataset size.

Durability: a case is committed atomically (result + outputs + judge rows), so a crashed/restarted
run resumes by skipping cases that already have a result.
"""

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.evaluation.calls import LLMCallError, ProviderGate, call_llm
from app.evaluation.config import RunConfig
from app.evaluation.judge import (
    JudgeConfig,
    JudgeError,
    NormalizedJudgement,
    RubricSpec,
    combine_passes,
    plan_passes,
    run_judge_pass,
)
from app.evaluation.providers import ProviderBuilder
from app.jobs.queue import heartbeat, utcnow
from app.models.evaluation import (
    CandidateOutput,
    EvaluationCase,
    EvaluationResult,
    EvaluationRun,
    JudgeEvaluation,
    Rubric,
    RubricScore,
)
from app.models.prompt import PromptVersion
from app.promptops.templates import TemplateError, render_template
from app.providers.base import BaseLLMProvider
from app.providers.models import GenerationParams

logger = structlog.get_logger(__name__)

GENERATION_KEYS = ("temperature", "max_tokens", "top_p", "frequency_penalty", "presence_penalty")


@dataclass
class VersionSpec:
    id: uuid.UUID
    semantic_version: str
    template: str
    provider_config: dict[str, Any]


@dataclass
class CaseSpec:
    id: uuid.UUID
    input_text: str
    expected_behavior: dict[str, Any]


@dataclass
class RunPlan:
    run_id: uuid.UUID
    provider: str
    model: str
    judge: JudgeConfig
    rubric: RubricSpec
    config: RunConfig
    versions: dict[str, VersionSpec]  # "A" / "B"
    pending_cases: list[CaseSpec]
    total_cases: int


@dataclass
class OutputData:
    slot: str
    version: VersionSpec
    rendered_prompt: str
    params: dict[str, Any]
    started_at: datetime
    completed_at: datetime
    status: str
    error: str | None = None
    text: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost: float = 0.0
    latency_ms: float = 0.0
    attempts: int = 1


def generation_params(version: VersionSpec) -> GenerationParams:
    cfg = {
        k: version.provider_config[k]
        for k in GENERATION_KEYS
        if version.provider_config.get(k) is not None
    }
    return GenerationParams(**cfg)


class RunExecutor:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        provider_builder: ProviderBuilder,
        *,
        worker_id: str,
        heartbeat_interval: float = 5.0,
        sleep=asyncio.sleep,
    ):
        self.session_factory = session_factory
        self.provider_builder = provider_builder
        self.worker_id = worker_id
        self.heartbeat_interval = heartbeat_interval
        self.sleep = sleep
        self.gate: ProviderGate | None = None

    # ---- entry point -------------------------------------------------------------------------
    async def execute(self, run_id: uuid.UUID) -> str:
        """Run to a terminal state. CancelledError (process shutdown) leaves the run RUNNING so
        it is recovered later; everything else ends in COMPLETED / FAILED / CANCELLED."""
        providers: list[BaseLLMProvider] = []
        try:
            plan = await self._load_plan(run_id)
            candidate = self.provider_builder(plan.provider, plan.model)
            providers.append(candidate)
            if (plan.judge.provider, plan.judge.model) == (plan.provider, plan.model):
                judge_provider = candidate
            else:
                judge_provider = self.provider_builder(plan.judge.provider, plan.judge.model)
                providers.append(judge_provider)
            cancelled = await self._run_cases(plan, candidate, judge_provider)
            return await self._finalize(plan, cancelled)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            await logger.aexception("Evaluation run crashed", run_id=str(run_id))
            await self._set_terminal(run_id, "FAILED", f"{exc.__class__.__name__}: {exc}")
            return "FAILED"
        finally:
            for p in providers:
                try:
                    await p.close()
                except Exception:  # noqa: BLE001
                    pass

    # ---- planning ----------------------------------------------------------------------------
    async def _load_plan(self, run_id: uuid.UUID) -> RunPlan:
        async with self.session_factory() as s:
            run = await s.get(EvaluationRun, run_id)
            if run is None:
                raise RuntimeError(f"run {run_id} not found")
            rubric = await s.get(Rubric, run.rubric_id)
            versions = {}
            for slot, vid in (("A", run.prompt_version_a_id), ("B", run.prompt_version_b_id)):
                v = await s.get(PromptVersion, vid)
                versions[slot] = VersionSpec(
                    v.id, v.semantic_version, v.template, dict(v.provider_config)
                )
            cases = (
                (
                    await s.execute(
                        select(EvaluationCase)
                        .where(EvaluationCase.dataset_id == run.dataset_id)
                        .order_by(EvaluationCase.ordinal.asc())
                    )
                )
                .scalars()
                .all()
            )
            done = set(
                (
                    await s.execute(
                        select(EvaluationResult.evaluation_case_id).where(
                            EvaluationResult.evaluation_run_id == run_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            cfg = RunConfig.from_dict(run.config)
            jd = (run.config or {}).get("judge", {})
            judge = JudgeConfig(
                provider=run.judge_provider,
                model=run.judge_model,
                max_attempts=cfg.judge_max_attempts,
                temperature=cfg.judge_temperature,
                include_prompts=cfg.judge_include_prompts,
                position_strategy=cfg.judge_position_strategy,  # type: ignore[arg-type]
                **{k: v for k, v in jd.items() if k == "max_tokens"},
            )
            # Cases are pinned at run creation via total_cases; cases added later are ignored.
            eligible = cases[: run.total_cases] if run.total_cases else cases
            return RunPlan(
                run_id=run.id,
                provider=run.provider,
                model=run.model,
                judge=judge,
                rubric=RubricSpec(
                    id=rubric.id,
                    name=rubric.name,
                    version=rubric.version,
                    scale_min=rubric.scale_min,
                    scale_max=rubric.scale_max,
                    criteria=list(rubric.criteria),
                ),
                config=cfg,
                versions=versions,
                pending_cases=[
                    CaseSpec(c.id, c.input_text, dict(c.expected_behavior))
                    for c in eligible
                    if c.id not in done
                ],
                total_cases=len(eligible),
            )

    # ---- execution ---------------------------------------------------------------------------
    async def _run_cases(  # noqa: C901 - orchestration is clearer in one method than split
        self, plan: RunPlan, candidate: BaseLLMProvider, judge_provider: BaseLLMProvider
    ) -> bool:
        cfg = plan.config
        self.gate = gate = ProviderGate(cfg.max_inflight_requests, cfg.requests_per_second)
        queue: asyncio.Queue[CaseSpec] = asyncio.Queue()
        for case in plan.pending_cases:
            queue.put_nowait(case)
        cancel_event = asyncio.Event()

        async def case_worker() -> None:
            while not cancel_event.is_set():
                try:
                    case = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                await self._process_case(plan, case, gate, candidate, judge_provider)

        async def heartbeat_loop() -> None:
            while True:
                await self.sleep(self.heartbeat_interval)
                async with self.session_factory() as s:
                    owned, cancel = await heartbeat(s, plan.run_id, self.worker_id)
                if cancel or not owned:
                    cancel_event.set()
                    return

        workers = [
            asyncio.create_task(case_worker(), name=f"case-worker-{i}")
            for i in range(max(1, min(cfg.case_concurrency, len(plan.pending_cases) or 1)))
        ]
        hb = asyncio.create_task(heartbeat_loop(), name="heartbeat")
        cancel_wait = asyncio.create_task(cancel_event.wait(), name="cancel-watch")
        all_workers = asyncio.gather(*workers)
        try:
            await asyncio.wait({all_workers, cancel_wait}, return_when=asyncio.FIRST_COMPLETED)
            if cancel_event.is_set() and not all_workers.done():
                all_workers.cancel()
            await asyncio.gather(all_workers, return_exceptions=True)
            # A worker exception (bug) must not be swallowed.
            for w in workers:
                if w.done() and not w.cancelled() and w.exception():
                    raise w.exception()  # type: ignore[misc]
        finally:
            for t in (hb, cancel_wait, *workers):
                t.cancel()
            await asyncio.gather(hb, cancel_wait, *workers, return_exceptions=True)
        return cancel_event.is_set()

    async def _generate(
        self,
        plan: RunPlan,
        slot: str,
        case: CaseSpec,
        gate: ProviderGate,
        provider: BaseLLMProvider,
    ) -> OutputData:
        version = plan.versions[slot]
        started = utcnow()
        params = generation_params(version)
        try:
            rendered = render_template(version.template, {"input": case.input_text})
        except TemplateError as exc:
            return OutputData(
                slot,
                version,
                version.template,
                params.model_dump(),
                started,
                utcnow(),
                "FAILED",
                error=f"template_error: {exc}",
                attempts=0,
            )
        cfg = plan.config
        try:
            result = await call_llm(
                provider,
                gate,
                prompt=rendered,
                params=params,
                timeout=cfg.call_timeout_s,
                max_retries=cfg.max_retries,
                backoff_base=cfg.backoff_base_s,
                sleep=self.sleep,
            )
        except LLMCallError as exc:
            return OutputData(
                slot,
                version,
                rendered,
                params.model_dump(),
                started,
                utcnow(),
                "FAILED",
                error=str(exc),
                attempts=exc.attempts,
            )
        r = result.response
        usage = r.token_usage
        return OutputData(
            slot,
            version,
            rendered,
            params.model_dump(),
            started,
            utcnow(),
            "COMPLETED",
            text=r.content,
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            total_tokens=usage.total_tokens if usage else 0,
            cost=r.estimated_cost or 0.0,
            latency_ms=r.latency_ms,
            attempts=result.attempts,
        )

    async def _process_case(
        self,
        plan: RunPlan,
        case: CaseSpec,
        gate: ProviderGate,
        candidate: BaseLLMProvider,
        judge_provider: BaseLLMProvider,
    ) -> None:
        cfg = plan.config
        out_a, out_b = await asyncio.gather(  # A and B run concurrently
            self._generate(plan, "A", case, gate, candidate),
            self._generate(plan, "B", case, gate, candidate),
        )
        judgements: list[NormalizedJudgement] = []
        judge_failures: list[dict[str, Any]] = []
        error: str | None = None

        if out_a.status != "COMPLETED" or out_b.status != "COMPLETED":
            failed = [o for o in (out_a, out_b) if o.status != "COMPLETED"]
            error = "; ".join(f"candidate {o.slot} failed: {o.error}" for o in failed)
        else:
            flags = plan_passes(plan.judge.position_strategy, f"{plan.run_id}:{case.id}")

            async def one_pass(index: int, swapped: bool):
                try:
                    return (
                        index,
                        swapped,
                        await run_judge_pass(
                            provider=judge_provider,
                            gate=gate,
                            rubric=plan.rubric,
                            config=plan.judge,
                            input_text=case.input_text,
                            expected_behavior=case.expected_behavior,
                            output_a=out_a.text or "",
                            output_b=out_b.text or "",
                            prompt_a=out_a.rendered_prompt,
                            prompt_b=out_b.rendered_prompt,
                            swapped=swapped,
                            pass_index=index,
                            timeout=cfg.call_timeout_s,
                            max_retries=cfg.max_retries,
                            backoff_base=cfg.backoff_base_s,
                            sleep=self.sleep,
                        ),
                    )
                except JudgeError as exc:
                    return index, swapped, exc

            for index, swapped, res in await asyncio.gather(
                *(one_pass(i, f) for i, f in enumerate(flags))
            ):
                if isinstance(res, JudgeError):
                    judge_failures.append({"index": index, "swapped": swapped, "error": res})
                else:
                    judgements.append(res)
            if judge_failures:
                error = "judge failed: " + "; ".join(f["error"].message for f in judge_failures)

        await self._persist_case(plan, case, out_a, out_b, judgements, judge_failures, error)

    async def _persist_case(
        self,
        plan: RunPlan,
        case: CaseSpec,
        out_a: OutputData,
        out_b: OutputData,
        judgements: list[NormalizedJudgement],
        failures: list[dict[str, Any]],
        error: str | None,
    ) -> None:
        combined = combine_passes(judgements) if judgements and not error else None
        async with self.session_factory() as s:
            result = EvaluationResult(
                evaluation_run_id=plan.run_id,
                evaluation_case_id=case.id,
                status="FAILED" if error else "COMPLETED",
                error=error,
                winner=combined.winner if combined else None,
                score_a=combined.score_a if combined else None,
                score_b=combined.score_b if combined else None,
                confidence=combined.confidence if combined else None,
                position_consistent=combined.position_consistent if combined else None,
            )
            s.add(result)
            try:
                await s.flush()
            except IntegrityError:  # already persisted by an earlier attempt of this run
                await s.rollback()
                return
            for o in (out_a, out_b):
                s.add(
                    CandidateOutput(
                        evaluation_run_id=plan.run_id,
                        evaluation_case_id=case.id,
                        result_id=result.id,
                        slot=o.slot,
                        prompt_version_id=o.version.id,
                        status=o.status,
                        error=o.error,
                        rendered_prompt=o.rendered_prompt,
                        output_text=o.text,
                        provider=plan.provider,
                        model=plan.model,
                        generation_params=o.params,
                        prompt_tokens=o.prompt_tokens,
                        completion_tokens=o.completion_tokens,
                        total_tokens=o.total_tokens,
                        estimated_cost=o.cost,
                        latency_ms=o.latency_ms,
                        attempts=o.attempts,
                        started_at=o.started_at,
                        completed_at=o.completed_at,
                    )
                )
            base = {
                "result_id": result.id,
                "evaluation_run_id": plan.run_id,
                "judge_provider": plan.judge.provider,
                "judge_model": plan.judge.model,
                "rubric_id": plan.rubric.id,
                "rubric_version": plan.rubric.version,
            }
            for j in judgements:
                je = JudgeEvaluation(
                    **base,
                    pass_index=j.pass_index,
                    swapped=j.swapped,
                    status="COMPLETED",
                    raw_response=j.raw_response,
                    raw_score=j.raw_score,
                    winner=j.winner,
                    score_a=j.score_a,
                    score_b=j.score_b,
                    normalized_score_a=j.normalized_a,
                    normalized_score_b=j.normalized_b,
                    confidence=j.confidence,
                    reasoning=j.reasoning,
                    attempts=j.attempts,
                    prompt_tokens=j.prompt_tokens,
                    completion_tokens=j.completion_tokens,
                    estimated_cost=j.estimated_cost,
                    latency_ms=j.latency_ms,
                    judged_at=utcnow(),
                )
                s.add(je)
                await s.flush()
                for name, c in j.criteria.items():
                    s.add(
                        RubricScore(
                            judge_evaluation_id=je.id,
                            criterion=name,
                            score_a=c["score_a"],
                            score_b=c["score_b"],
                            reason=c["reason"],
                        )
                    )
            for f in failures:
                err: JudgeError = f["error"]
                s.add(
                    JudgeEvaluation(
                        **base,
                        pass_index=f["index"],
                        swapped=f["swapped"],
                        status="FAILED",
                        error=err.message,
                        raw_response=err.raw_response,
                        attempts=err.attempts,
                        prompt_tokens=int(err.usage.get("prompt_tokens", 0)),
                        completion_tokens=int(err.usage.get("completion_tokens", 0)),
                        estimated_cost=float(err.usage.get("estimated_cost", 0.0)),
                        latency_ms=float(err.usage.get("latency_ms", 0.0)),
                        judged_at=utcnow(),
                    )
                )
            await s.commit()

    # ---- completion --------------------------------------------------------------------------
    async def _finalize(self, plan: RunPlan, cancelled: bool) -> str:
        async with self.session_factory() as s:
            counts = dict(
                (
                    await s.execute(
                        select(EvaluationResult.status, func.count())
                        .where(EvaluationResult.evaluation_run_id == plan.run_id)
                        .group_by(EvaluationResult.status)
                    )
                ).all()
            )
        ok, failed = counts.get("COMPLETED", 0), counts.get("FAILED", 0)
        if cancelled:
            status, error = "CANCELLED", None
        elif ok == 0:
            status, error = "FAILED", f"No case completed ({failed} failed)"
        else:
            status, error = (
                "COMPLETED",
                (f"{failed} of {plan.total_cases} cases failed" if failed else None),
            )
        await self._set_terminal(plan.run_id, status, error)
        return status

    async def _set_terminal(self, run_id: uuid.UUID, status: str, error: str | None) -> None:
        async with self.session_factory() as s:
            await s.execute(
                update(EvaluationRun)
                .where(EvaluationRun.id == run_id)
                .values(status=status, error=error, completed_at=utcnow(), locked_by=None)
            )
            await s.commit()
