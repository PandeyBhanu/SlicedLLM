from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings


def make_engine(url: str, **kwargs) -> AsyncEngine:
    return create_async_engine(url, pool_pre_ping=True, **kwargs)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


async_engine = make_engine(settings.DATABASE_URL, pool_size=20, max_overflow=10)  # type: ignore[arg-type]
async_session_maker = make_session_factory(async_engine)


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Indirection so tests / workers can be pointed at another database."""
    return async_session_maker


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: one session per request, rolled back on error."""
    async with get_session_factory()() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
