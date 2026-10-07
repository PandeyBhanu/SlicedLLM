import secrets
from collections.abc import AsyncGenerator

from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.context import AuditContext
from app.core.exceptions import AuthenticationError
from app.db.session import get_async_session
from app.services.evaluation import EvaluationService
from app.services.prompt import PromptService


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """One database session per request."""
    async for session in get_async_session():
        yield session


async def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """If `API_KEY` is configured every API call must present it. Otherwise the API is open."""
    if settings.API_KEY and not (x_api_key and secrets.compare_digest(x_api_key, settings.API_KEY)):
        raise AuthenticationError()


async def get_audit_context(
    request: Request, x_actor_id: str | None = Header(default=None)
) -> AuditContext:
    """Actor identity is taken from `X-Actor-Id`. It is *asserted*, not authenticated: real user
    authentication (OIDC/JWT) would replace this dependency without touching any service."""
    actor = (x_actor_id or "anonymous").strip()[:255] or "anonymous"
    return AuditContext(actor_id=actor, request_id=getattr(request.state, "request_id", None))


def get_prompt_service(
    db: AsyncSession = Depends(get_db), ctx: AuditContext = Depends(get_audit_context)
) -> PromptService:
    return PromptService(db, ctx)


def get_evaluation_service(
    db: AsyncSession = Depends(get_db), ctx: AuditContext = Depends(get_audit_context)
) -> EvaluationService:
    return EvaluationService(db, ctx)
