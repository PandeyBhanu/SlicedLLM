from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

# Create async engine with robust connection pooling config
async_engine = create_async_engine(
    settings.DATABASE_URL,  # type: ignore
    echo=False,  # Set to True only for verbose debugging
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,  # Automatically check connection health
)

# Async session maker
async_session_maker = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,  # Essential for async SQLAlchemy
)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI Dependency for yielding db sessions.
    
    Ensures rollback on exceptions and final cleanup on request completion.
    """
    async with async_session_maker() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
