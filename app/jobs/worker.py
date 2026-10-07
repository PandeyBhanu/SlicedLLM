"""Polling worker that executes evaluation runs outside any HTTP request.

It owns its own database sessions (never a request-scoped one). It can run inside the API process
(`RUN_WORKER_IN_APP=true`, started from the FastAPI lifespan) or standalone: `python -m app.jobs`.
"""

import asyncio
import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.evaluation.providers import ProviderBuilder, default_provider_builder
from app.evaluation.runner import RunExecutor
from app.jobs.queue import claim_next_run, recover_interrupted

logger = structlog.get_logger(__name__)


class JobWorker:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        provider_builder: ProviderBuilder = default_provider_builder,
        *,
        worker_id: str | None = None,
        poll_interval: float | None = None,
        heartbeat_interval: float | None = None,
        stale_after_s: float | None = None,
        max_attempts: int | None = None,
        sleep=asyncio.sleep,
    ):
        self.session_factory = session_factory
        self.provider_builder = provider_builder
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self.poll_interval = settings.JOB_POLL_INTERVAL if poll_interval is None else poll_interval
        self.heartbeat_interval = (
            settings.JOB_HEARTBEAT_INTERVAL if heartbeat_interval is None else heartbeat_interval
        )
        self.stale_after_s = settings.JOB_STALE_SECONDS if stale_after_s is None else stale_after_s
        self.max_attempts = settings.JOB_MAX_ATTEMPTS if max_attempts is None else max_attempts
        self.sleep = sleep
        self._stop = asyncio.Event()

    async def recover_on_startup(self) -> None:
        """Single-worker assumption: any RUNNING run at boot belongs to a dead process."""
        async with self.session_factory() as s:
            await recover_interrupted(
                s, stale_after_s=0, max_attempts=self.max_attempts, exclude_worker=self.worker_id
            )

    async def run_once(self) -> bool:
        """Recover stale runs, then claim and fully execute at most one run. True if one ran."""
        async with self.session_factory() as s:
            await recover_interrupted(
                s, stale_after_s=self.stale_after_s, max_attempts=self.max_attempts
            )
        async with self.session_factory() as s:
            run_id = await claim_next_run(s, self.worker_id)
        if run_id is None:
            return False
        await logger.ainfo("Claimed evaluation run", run_id=str(run_id), worker=self.worker_id)
        executor = RunExecutor(
            self.session_factory,
            self.provider_builder,
            worker_id=self.worker_id,
            heartbeat_interval=self.heartbeat_interval,
        )
        status = await executor.execute(run_id)
        await logger.ainfo("Evaluation run finished", run_id=str(run_id), status=status)
        return True

    async def run_forever(self) -> None:
        if settings.JOB_RECOVER_ON_STARTUP:
            await self.recover_on_startup()
        while not self._stop.is_set():
            try:
                worked = await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - keep the worker alive
                await logger.aexception("Worker iteration failed")
                worked = False
            if not worked:
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=self.poll_interval)
                except TimeoutError:
                    pass

    def stop(self) -> None:
        self._stop.set()
