"""Test fixtures. Database behaviour (triggers, partial unique indexes, JSONB, row locks,
SKIP LOCKED) only exists in PostgreSQL, so tests run against a real PostgreSQL database -
never SQLite.

Point `TEST_DATABASE_URL` at a *disposable* database (its public schema is dropped per test), e.g.
    postgresql+asyncpg://postgres:postgres@localhost:5432/slicedllm_test
The database is created automatically if it does not exist.
"""

import os

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("RUN_WORKER_IN_APP", "false")
os.environ.setdefault("AUTO_CREATE_SCHEMA", "false")
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/slicedllm_test"
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

import asyncio  # noqa: E402
from collections.abc import AsyncGenerator  # noqa: E402

import asyncpg  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool  # noqa: E402

import app.db.session as db_session_module  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.main import app  # noqa: E402


def _ensure_database() -> None:
    url = make_url(TEST_DATABASE_URL)

    async def go() -> None:
        conn = await asyncpg.connect(
            user=url.username,
            password=url.password,
            host=url.host,
            port=url.port or 5432,
            database="postgres",
        )
        try:
            exists = await conn.fetchval(
                "SELECT 1 FROM pg_database WHERE datname = $1", url.database
            )
            if not exists:
                await conn.execute(f'CREATE DATABASE "{url.database}"')
        finally:
            await conn.close()

    asyncio.run(go())


async def _reset_schema() -> None:
    eng = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    async with eng.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.run_sync(Base.metadata.create_all)
    await eng.dispose()


@pytest.fixture(scope="session", autouse=True)
def _database() -> None:
    """Create the test database (if needed) and a fresh schema once per session."""
    try:
        _ensure_database()
        asyncio.run(_reset_schema())
    except Exception as exc:  # noqa: BLE001
        pytest.exit(
            f"PostgreSQL not reachable at TEST_DATABASE_URL ({exc}). See tests/conftest.py.",
            returncode=2,
        )


@pytest_asyncio.fixture
async def engine() -> AsyncGenerator:
    """Empty tables for every test. One pool per test: it is disposed in the same event loop."""
    eng = create_async_engine(TEST_DATABASE_URL, pool_size=10, max_overflow=20)
    yield eng
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    async with eng.begin() as conn:
        # Tests may disable triggers to simulate a privileged attacker; always restore them.
        await conn.execute(text("ALTER TABLE prompt_versions ENABLE TRIGGER ALL"))
        await conn.execute(text("ALTER TABLE audit_logs ENABLE TRIGGER ALL"))
        # Replica role skips the append-only triggers so the audit table can be reset between tests.
        await conn.execute(text("SET LOCAL session_replication_role = replica"))
        await conn.execute(text(f"TRUNCATE {tables} CASCADE"))
    await eng.dispose()


@pytest.fixture
def session_factory(engine, monkeypatch) -> async_sessionmaker[AsyncSession]:
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session_module, "async_session_maker", factory)
    return factory


@pytest_asyncio.fixture
async def db(session_factory) -> AsyncGenerator[AsyncSession, None]:
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def client(session_factory) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as ac:
        yield ac
