from typing import AsyncGenerator
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_async_session
from app.services.evaluation import EvaluationService
from app.services.prompt import PromptService


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency injecting a standard async database session."""
    async for session in get_async_session():
        yield session


def get_prompt_service(db: AsyncSession = Depends(get_db)) -> PromptService:
    """Dependency injecting the Prompt Management service layer."""
    return PromptService(db)


def get_evaluation_service(db: AsyncSession = Depends(get_db)) -> EvaluationService:
    """Dependency injecting the Evaluation orchestration service layer."""
    return EvaluationService(db)
