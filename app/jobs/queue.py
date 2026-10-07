"""Database-backed job queue. The `evaluation_runs` table *is* the queue.

States:  PENDING -> RUNNING -> COMPLETED | FAILED | CANCELLED
* claim: `SELECT ... FOR UPDATE SKIP LOCKED` picks one PENDING run, so concurrent workers never
  take the same run.
* heartbeat: a running worker refreshes `heartbeat_at` and learns about `cancel_requested`.
* recovery: RUNNING runs with a stale heartbeat were abandoned by a dead worker; they go back to
  PENDING (resumable - finished cases are skipped) until `max_attempts`, then FAILED.
"""

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.evaluation import EvaluationRun

logger = structlog.get_logger(__name__)


def utcnow() -> datetime:
    return datetime.now(UTC)


async def claim_next_run(session: AsyncSession, worker_id: str) -> uuid.UUID | None:
    run = (
        (
            await session.execute(
                select(EvaluationRun)
                .where(EvaluationRun.status == "PENDING")
                .order_by(EvaluationRun.created_at.asc())
                .with_for_update(skip_locked=True)
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    if not run:
        await session.rollback()
        return None
    now = utcnow()
    run.status = "RUNNING"
    run.locked_by = worker_id
    run.heartbeat_at = now
    run.attempts += 1
    run.started_at = run.started_at or now
    run_id = run.id
    await session.commit()
    return run_id


async def heartbeat(session: AsyncSession, run_id: uuid.UUID, worker_id: str) -> tuple[bool, bool]:
    """-> (still_owned, cancel_requested)."""
    row = (
        await session.execute(
            update(EvaluationRun)
            .where(
                EvaluationRun.id == run_id,
                EvaluationRun.locked_by == worker_id,
                EvaluationRun.status == "RUNNING",
            )
            .values(heartbeat_at=utcnow())
            .returning(EvaluationRun.cancel_requested)
        )
    ).first()
    await session.commit()
    return (row is not None, bool(row[0]) if row else False)


async def recover_interrupted(
    session: AsyncSession,
    *,
    stale_after_s: float,
    max_attempts: int,
    exclude_worker: str | None = None,
) -> list[tuple[uuid.UUID, str]]:
    """Requeue (or fail) RUNNING runs whose worker stopped heart-beating.

    `stale_after_s=0` treats every RUNNING run not owned by `exclude_worker` as abandoned; only
    safe when a single worker process exists (startup recovery).
    """
    cutoff = utcnow() - timedelta(seconds=stale_after_s)
    query = (
        select(EvaluationRun)
        .where(EvaluationRun.status == "RUNNING")
        .with_for_update(skip_locked=True)
    )
    if stale_after_s > 0:
        query = query.where(
            (EvaluationRun.heartbeat_at.is_(None)) | (EvaluationRun.heartbeat_at < cutoff)
        )
    if exclude_worker:
        query = query.where(
            (EvaluationRun.locked_by.is_(None)) | (EvaluationRun.locked_by != exclude_worker)
        )
    changes: list[tuple[uuid.UUID, str]] = []
    for run in (await session.execute(query)).scalars().all():
        if run.cancel_requested:
            run.status, run.completed_at = "CANCELLED", utcnow()
        elif run.attempts >= max_attempts:
            run.status, run.completed_at = "FAILED", utcnow()
            run.error = f"Interrupted {run.attempts} times (worker died); giving up"
        else:
            run.status = "PENDING"
        run.locked_by = None
        changes.append((run.id, run.status))
    await session.commit()
    for run_id, status in changes:
        await logger.awarning(
            "Recovered interrupted evaluation run", run_id=str(run_id), new_status=status
        )
    return changes
