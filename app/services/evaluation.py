import uuid
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.audit import AuditService
from app.core.config import settings
from app.core.context import AuditContext
from app.core.exceptions import EntityNotFoundException, ValidationError
from app.evaluation.config import RunConfig
from app.evaluation.rubrics import (
    DEFAULT_CRITERIA,
    DEFAULT_RUBRIC_NAME,
    DEFAULT_RUBRIC_VERSION,
    SCALE_MAX,
    SCALE_MIN,
    rubric_hash,
    validate_criteria,
)
from app.evaluation.summary import criterion_means, mean, percentile, wilson_interval
from app.jobs.queue import utcnow
from app.models.evaluation import (
    TERMINAL_RUN_STATUSES,
    CandidateOutput,
    EvaluationCase,
    EvaluationDataset,
    EvaluationResult,
    EvaluationRun,
    JudgeEvaluation,
    Rubric,
    RubricScore,
)
from app.models.prompt import PromptVersion
from app.providers import ProviderRegistry
from app.schemas.evaluation import (
    EvaluationCaseCreate,
    EvaluationDatasetCreate,
    EvaluationRunCreate,
    RubricCreate,
)

logger = structlog.get_logger(__name__)


class EvaluationService:
    """Request-path operations: datasets, rubrics, enqueueing runs and reading results.

    Executing a run is NOT done here - `EvaluationService.create_run` only writes a PENDING row;
    the `JobWorker` (app/jobs) picks it up with its own database session.
    """

    def __init__(self, db: AsyncSession, ctx: AuditContext | None = None):
        self.db = db
        self.ctx = ctx or AuditContext()
        self.audit = AuditService(db)

    # ---- datasets ----------------------------------------------------------------------------
    async def create_dataset(self, schema: EvaluationDatasetCreate) -> EvaluationDataset:
        existing = (
            (
                await self.db.execute(
                    select(EvaluationDataset).where(EvaluationDataset.name == schema.name)
                )
            )
            .scalars()
            .first()
        )
        if existing:
            raise ValidationError(f"Evaluation dataset '{schema.name}' already exists.")
        dataset = EvaluationDataset(**schema.model_dump())
        self.db.add(dataset)
        await self.db.commit()
        return dataset

    async def add_case_to_dataset(
        self, dataset_id: uuid.UUID, schema: EvaluationCaseCreate
    ) -> EvaluationCase:
        dataset = (
            (
                await self.db.execute(
                    select(EvaluationDataset)
                    .where(EvaluationDataset.id == dataset_id)
                    .with_for_update()
                )
            )
            .scalars()
            .first()
        )
        if not dataset:
            raise EntityNotFoundException("Evaluation dataset not found.")
        next_ordinal = (
            await self.db.execute(
                select(func.coalesce(func.max(EvaluationCase.ordinal), -1) + 1).where(
                    EvaluationCase.dataset_id == dataset_id
                )
            )
        ).scalar_one()
        case = EvaluationCase(dataset_id=dataset_id, ordinal=next_ordinal, **schema.model_dump())
        self.db.add(case)
        await self.db.commit()
        return case

    async def get_dataset(self, dataset_id: uuid.UUID) -> dict[str, Any]:
        dataset = (
            (
                await self.db.execute(
                    select(EvaluationDataset)
                    .where(EvaluationDataset.id == dataset_id)
                    .options(selectinload(EvaluationDataset.cases))
                )
            )
            .scalars()
            .first()
        )
        if not dataset:
            raise EntityNotFoundException("Evaluation dataset not found.")
        return {
            "id": dataset.id,
            "name": dataset.name,
            "description": dataset.description,
            "created_at": dataset.created_at,
            "case_count": len(dataset.cases),
            "cases": dataset.cases,
        }

    async def list_datasets(self, skip: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        rows = (
            await self.db.execute(
                select(EvaluationDataset, func.count(EvaluationCase.id))
                .outerjoin(EvaluationCase, EvaluationCase.dataset_id == EvaluationDataset.id)
                .group_by(EvaluationDataset.id)
                .order_by(EvaluationDataset.created_at.desc())
                .offset(skip)
                .limit(limit)
            )
        ).all()
        return [
            {
                "id": d.id,
                "name": d.name,
                "description": d.description,
                "created_at": d.created_at,
                "case_count": n,
            }
            for d, n in rows
        ]

    # ---- rubrics -----------------------------------------------------------------------------
    async def ensure_default_rubric(self) -> Rubric:
        rubric = (
            (
                await self.db.execute(
                    select(Rubric).where(
                        Rubric.name == DEFAULT_RUBRIC_NAME, Rubric.version == DEFAULT_RUBRIC_VERSION
                    )
                )
            )
            .scalars()
            .first()
        )
        if rubric:
            return rubric
        rubric = Rubric(
            name=DEFAULT_RUBRIC_NAME,
            version=DEFAULT_RUBRIC_VERSION,
            description="Default four-criterion rubric",
            scale_min=SCALE_MIN,
            scale_max=SCALE_MAX,
            criteria=DEFAULT_CRITERIA,
            definition_hash=rubric_hash(
                DEFAULT_RUBRIC_NAME, DEFAULT_RUBRIC_VERSION, DEFAULT_CRITERIA, SCALE_MIN, SCALE_MAX
            ),
        )
        self.db.add(rubric)
        await self.db.commit()
        return rubric

    async def create_rubric(self, schema: RubricCreate) -> Rubric:
        if schema.scale_max <= schema.scale_min:
            raise ValidationError("scale_max must be greater than scale_min")
        try:
            criteria = validate_criteria([c.model_dump() for c in schema.criteria])
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        latest = (
            await self.db.execute(
                select(func.max(Rubric.version)).where(Rubric.name == schema.name)
            )
        ).scalar_one()
        version = (latest or 0) + 1
        rubric = Rubric(
            name=schema.name,
            version=version,
            description=schema.description,
            scale_min=schema.scale_min,
            scale_max=schema.scale_max,
            criteria=criteria,
            definition_hash=rubric_hash(
                schema.name, version, criteria, schema.scale_min, schema.scale_max
            ),
        )
        self.db.add(rubric)
        await self.db.commit()
        return rubric

    async def list_rubrics(self) -> list[Rubric]:
        await self.ensure_default_rubric()
        return list(
            (await self.db.execute(select(Rubric).order_by(Rubric.name, Rubric.version.desc())))
            .scalars()
            .all()
        )

    # ---- runs --------------------------------------------------------------------------------
    async def create_run(self, schema: EvaluationRunCreate) -> dict[str, Any]:
        dataset = await self.get_dataset(schema.dataset_id)
        case_count = dataset["case_count"]
        if case_count == 0:
            raise ValidationError("Evaluation dataset must have at least one test case.")
        if case_count > settings.EVALUATION_MAX_CASES_PER_RUN:
            raise ValidationError(
                f"Dataset has {case_count} cases; the limit per run is "
                f"{settings.EVALUATION_MAX_CASES_PER_RUN}."
            )
        for label, vid in (("A", schema.prompt_version_a_id), ("B", schema.prompt_version_b_id)):
            if await self.db.get(PromptVersion, vid) is None:
                raise EntityNotFoundException(f"Prompt version {label} not found.")

        judge_provider = schema.judge_provider or settings.DEFAULT_JUDGE_PROVIDER or schema.provider
        judge_model = schema.judge_model or settings.DEFAULT_JUDGE_MODEL or schema.model
        for name in {schema.provider, judge_provider}:
            if ProviderRegistry.get_provider_class(name) is None:
                raise ValidationError(
                    f"Unknown provider '{name}'. "
                    f"Available: {', '.join(ProviderRegistry.list_providers())}"
                )
        if schema.rubric_id:
            rubric = await self.db.get(Rubric, schema.rubric_id)
            if rubric is None:
                raise EntityNotFoundException("Rubric not found.")
        else:
            rubric = await self.ensure_default_rubric()

        config = RunConfig.from_overrides(schema.settings.model_dump(exclude_none=True)).to_dict()
        run = EvaluationRun(
            dataset_id=schema.dataset_id,
            prompt_version_a_id=schema.prompt_version_a_id,
            prompt_version_b_id=schema.prompt_version_b_id,
            rubric_id=rubric.id,
            provider=schema.provider,
            model=schema.model,
            judge_provider=judge_provider,
            judge_model=judge_model,
            config=config,
            status="PENDING",
            total_cases=case_count,
            created_by=self.ctx.actor_id,
        )
        self.db.add(run)
        await self.db.flush()
        await self.audit.append(
            entity_type="EvaluationRun",
            entity_id=run.id,
            action="CREATE",
            ctx=self.ctx,
            after_state={
                "dataset_id": str(run.dataset_id),
                "prompt_version_a_id": str(run.prompt_version_a_id),
                "prompt_version_b_id": str(run.prompt_version_b_id),
                "provider": run.provider,
                "model": run.model,
                "judge_provider": judge_provider,
                "judge_model": judge_model,
                "rubric": f"{rubric.name}@{rubric.version}",
                "config": config,
            },
        )
        await self.db.commit()
        return await self.get_run(run.id)

    async def _run_row(self, run_id: uuid.UUID) -> EvaluationRun:
        run = await self.db.get(EvaluationRun, run_id)
        if not run:
            raise EntityNotFoundException("Evaluation run not found.")
        return run

    async def _progress(self, run_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, int]]:
        rows = (
            await self.db.execute(
                select(EvaluationResult.evaluation_run_id, EvaluationResult.status, func.count())
                .where(EvaluationResult.evaluation_run_id.in_(run_ids))
                .group_by(EvaluationResult.evaluation_run_id, EvaluationResult.status)
            )
        ).all()
        out: dict[uuid.UUID, dict[str, int]] = {
            rid: {"COMPLETED": 0, "FAILED": 0} for rid in run_ids
        }
        for rid, status, n in rows:
            out[rid][status] = n
        return out

    async def _decorate(self, runs: list[EvaluationRun]) -> list[dict[str, Any]]:
        if not runs:
            return []
        version_ids = {r.prompt_version_a_id for r in runs} | {r.prompt_version_b_id for r in runs}
        labels = dict(
            (
                await self.db.execute(
                    select(PromptVersion.id, PromptVersion.semantic_version).where(
                        PromptVersion.id.in_(version_ids)
                    )
                )
            ).all()
        )
        names = dict(
            (
                await self.db.execute(
                    select(EvaluationDataset.id, EvaluationDataset.name).where(
                        EvaluationDataset.id.in_({r.dataset_id for r in runs})
                    )
                )
            ).all()
        )
        progress = await self._progress([r.id for r in runs])
        out = []
        for r in runs:
            p = progress[r.id]
            out.append(
                {
                    **{c.name: getattr(r, c.name) for c in EvaluationRun.__table__.columns},
                    "version_a_label": labels.get(r.prompt_version_a_id),
                    "version_b_label": labels.get(r.prompt_version_b_id),
                    "dataset_name": names.get(r.dataset_id),
                    "progress": {
                        "total_cases": r.total_cases,
                        "completed_cases": p["COMPLETED"],
                        "failed_cases": p["FAILED"],
                    },
                }
            )
        return out

    async def get_run(self, run_id: uuid.UUID) -> dict[str, Any]:
        return (await self._decorate([await self._run_row(run_id)]))[0]

    async def list_runs(self, skip: int = 0, limit: int = 50) -> list[dict[str, Any]]:
        runs = (
            (
                await self.db.execute(
                    select(EvaluationRun)
                    .order_by(EvaluationRun.created_at.desc())
                    .offset(skip)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return await self._decorate(list(runs))

    async def cancel_run(self, run_id: uuid.UUID) -> dict[str, Any]:
        run = (
            (
                await self.db.execute(
                    select(EvaluationRun).where(EvaluationRun.id == run_id).with_for_update()
                )
            )
            .scalars()
            .first()
        )
        if not run:
            raise EntityNotFoundException("Evaluation run not found.")
        if run.status in TERMINAL_RUN_STATUSES:
            raise ValidationError(f"Run is already {run.status}.")
        before = run.status
        run.cancel_requested = True
        if run.status == "PENDING":
            run.status = "CANCELLED"
            run.completed_at = utcnow()
        await self.db.flush()
        await self.db.refresh(run)
        await self.audit.append(
            entity_type="EvaluationRun",
            entity_id=run.id,
            action="CANCEL",
            ctx=self.ctx,
            before_state={"status": before},
            after_state={"status": run.status, "cancel_requested": True},
        )
        await self.db.commit()
        return await self.get_run(run_id)

    async def get_cases(self, run_id: uuid.UUID) -> list[dict[str, Any]]:
        await self._run_row(run_id)
        results = (
            await self.db.execute(
                select(EvaluationResult, EvaluationCase)
                .join(EvaluationCase, EvaluationCase.id == EvaluationResult.evaluation_case_id)
                .where(EvaluationResult.evaluation_run_id == run_id)
                .options(
                    selectinload(EvaluationResult.outputs),
                    selectinload(EvaluationResult.judge_evaluations).selectinload(
                        JudgeEvaluation.rubric_scores
                    ),
                )
                .order_by(EvaluationCase.ordinal.asc())
            )
        ).all()
        return [
            {
                "result_id": res.id,
                "case_id": case.id,
                "ordinal": case.ordinal,
                "input_text": case.input_text,
                "expected_behavior": case.expected_behavior,
                "status": res.status,
                "error": res.error,
                "winner": res.winner,
                "score_a": res.score_a,
                "score_b": res.score_b,
                "confidence": res.confidence,
                "position_consistent": res.position_consistent,
                "outputs": sorted(res.outputs, key=lambda o: o.slot),
                "judge_evaluations": res.judge_evaluations,
            }
            for res, case in results
        ]

    async def get_summary(self, run_id: uuid.UUID) -> dict[str, Any]:
        run = await self._run_row(run_id)
        rubric = await self.db.get(Rubric, run.rubric_id)
        results = list(
            (
                await self.db.execute(
                    select(EvaluationResult).where(EvaluationResult.evaluation_run_id == run_id)
                )
            )
            .scalars()
            .all()
        )
        outputs = list(
            (
                await self.db.execute(
                    select(CandidateOutput).where(CandidateOutput.evaluation_run_id == run_id)
                )
            )
            .scalars()
            .all()
        )
        judges = list(
            (
                await self.db.execute(
                    select(JudgeEvaluation).where(JudgeEvaluation.evaluation_run_id == run_id)
                )
            )
            .scalars()
            .all()
        )
        crit_rows = (
            await self.db.execute(
                select(RubricScore.criterion, RubricScore.score_a, RubricScore.score_b)
                .join(JudgeEvaluation, JudgeEvaluation.id == RubricScore.judge_evaluation_id)
                .where(
                    JudgeEvaluation.evaluation_run_id == run_id,
                    JudgeEvaluation.status == "COMPLETED",
                )
            )
        ).all()

        ok = [r for r in results if r.status == "COMPLETED"]
        wins_a = sum(1 for r in ok if r.winner == "A")
        wins_b = sum(1 for r in ok if r.winner == "B")
        ties = sum(1 for r in ok if r.winner == "TIE")
        decisive = wins_a + wins_b
        ci_low, ci_high = wilson_interval(wins_a, decisive)

        def slot_metrics(slot: str) -> dict[str, Any]:
            mine = [o for o in outputs if o.slot == slot]
            done = [o for o in mine if o.status == "COMPLETED"]
            lat = [o.latency_ms for o in done]
            scores = [
                getattr(r, f"score_{slot.lower()}")
                for r in ok
                if getattr(r, f"score_{slot.lower()}") is not None
            ]
            return {
                "outputs_completed": len(done),
                "outputs_failed": len(mine) - len(done),
                "avg_latency_ms": mean(lat),
                "p95_latency_ms": percentile(lat, 0.95),
                "prompt_tokens": sum(o.prompt_tokens for o in mine),
                "completion_tokens": sum(o.completion_tokens for o in mine),
                "total_tokens": sum(o.total_tokens for o in mine),
                "estimated_cost": sum(o.estimated_cost for o in mine),
                "avg_score": mean(scores),
            }

        slot_a, slot_b = slot_metrics("A"), slot_metrics("B")
        judge_cost = sum(j.estimated_cost for j in judges)
        n_ok = len(ok)
        return {
            "run_id": run.id,
            "status": run.status,
            "total_cases": run.total_cases,
            "completed_cases": n_ok,
            "failed_cases": len(results) - n_ok,
            "wins_a": wins_a,
            "wins_b": wins_b,
            "ties": ties,
            "win_rate_a": wins_a / n_ok if n_ok else None,
            "win_rate_b": wins_b / n_ok if n_ok else None,
            "tie_rate": ties / n_ok if n_ok else None,
            "a_share_of_decisive": wins_a / decisive if decisive else None,
            "a_share_ci_low": ci_low,
            "a_share_ci_high": ci_high,
            "avg_confidence": mean([r.confidence for r in ok if r.confidence is not None]),
            "position_consistency_rate": (
                sum(1 for r in ok if r.position_consistent) / n_ok if n_ok else None
            ),
            "rubric_scale_min": rubric.scale_min,
            "rubric_scale_max": rubric.scale_max,
            "slot_a": slot_a,
            "slot_b": slot_b,
            "criteria": [
                {"criterion": name, "avg_score_a": a, "avg_score_b": b, "samples": n}
                for name, (a, b, n) in sorted(
                    criterion_means([tuple(r) for r in crit_rows]).items()
                )
            ],
            "judge_tokens": sum(j.prompt_tokens + j.completion_tokens for j in judges),
            "judge_cost": judge_cost,
            "total_cost": slot_a["estimated_cost"] + slot_b["estimated_cost"] + judge_cost,
            "note": (
                "a_share_ci is a 95% Wilson interval over decisive (non-tie) cases; it treats "
                "cases as independent and does not account for judge noise."
            ),
        }
