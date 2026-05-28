import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
import structlog

from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import setup_logging
from app.api.v1.router import api_router

# Initialize logging structure
setup_logging()
logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Lifespan events
    await logger.ainfo("Starting SlicedLLM Backend Services...")
    yield
    await logger.ainfo("Shutting down SlicedLLM Backend Services...")


app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Production-grade AI PromptOps platform for versioning, rollback, evaluation, and LLM providers.",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.ENVIRONMENT != "production" else None,
    redoc_url="/redoc" if settings.ENVIRONMENT != "production" else None,
)

# CORS Middleware config
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Trace and Request-ID Logging Middleware
@app.middleware("http")
async def logging_middleware(request: Request, call_next: Any) -> Response:
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id)

    start_time = time.perf_counter()
    
    # Process request
    response = await call_next(request)
    
    duration = time.perf_counter() - start_time
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Process-Time"] = f"{duration:.4f}s"

    await logger.ainfo(
        "Request processed",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=round(duration * 1000, 2),
    )
    
    return response


# Register Application-Wide Custom Exceptions
register_exception_handlers(app)

# Register Versioned API Routes
app.include_router(api_router, prefix=settings.API_V1_STR)


# Root/Health check
@app.get("/health", tags=["Health"])
async def health_check() -> dict:
    return {
        "status": "healthy",
        "timestamp": time.time(),
        "environment": settings.ENVIRONMENT,
        "version": "1.0.0",
    }
