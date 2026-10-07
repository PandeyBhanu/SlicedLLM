import asyncio
import time
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import setup_logging
from app.db.session import async_engine, get_session_factory
from app.jobs.worker import JobWorker

setup_logging()
logger = structlog.get_logger(__name__)


async def init_schema() -> None:
    """Create tables + immutability/append-only triggers if missing (dev convenience)."""
    from app.db.base import Base

    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    await logger.ainfo("Starting SlicedLLM backend")
    if settings.AUTO_CREATE_SCHEMA:
        await init_schema()
    worker_task = None
    worker = None
    if settings.RUN_WORKER_IN_APP:
        worker = JobWorker(get_session_factory())
        worker_task = asyncio.create_task(worker.run_forever(), name="evaluation-worker")
    app.state.worker = worker
    try:
        yield
    finally:
        if worker_task:
            # Cancel rather than drain: an interrupted run stays RUNNING and is recovered on
            # next boot.
            worker_task.cancel()
            await asyncio.gather(worker_task, return_exceptions=True)
        await async_engine.dispose()
        await logger.ainfo("SlicedLLM backend stopped")


app = FastAPI(
    title=settings.PROJECT_NAME,
    description=(
        "LLM evaluation platform: versioned prompts, token diffs, audited changes, "
        "A/B runs judged by an LLM."
    ),
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.ENVIRONMENT != "production" else None,
    redoc_url="/redoc" if settings.ENVIRONMENT != "production" else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_context_middleware(request: Request, call_next: Any) -> Response:
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))[:100]
    request.state.request_id = request_id
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id)
    start = time.perf_counter()
    response = await call_next(request)
    duration = time.perf_counter() - start
    response.headers["X-Request-ID"] = request_id
    await logger.ainfo(
        "request",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=round(duration * 1000, 2),
    )
    return response


register_exception_handlers(app)
app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/health", tags=["Health"])
async def health_check() -> dict:
    return {"status": "healthy", "environment": settings.ENVIRONMENT, "version": app.version}
