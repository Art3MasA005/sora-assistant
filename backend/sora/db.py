"""Async SQLAlchemy engine and session helpers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from sora.config import get_settings


class Base(DeclarativeBase):
    # Fetch server-generated values (created_at, updated_at) on INSERT/UPDATE, so reading them later
    # doesn't trigger a lazy load outside the async context.
    __mapper_args__ = {"eager_defaults": True}


_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine, _sessionmaker
    if _engine is None:
        settings = get_settings()
        if not settings.database_url:
            raise RuntimeError("DATABASE_URL is not set in .env")
        from sora.wsl_db import ensure_postgres

        ensure_postgres()  # no-op unless WSL_DISTRO is set; wakes WSL so any script can use the DB
        _engine = create_async_engine(
            settings.async_database_url,
            pool_pre_ping=True,
            pool_size=5,
            # Fail fast instead of hanging when Postgres (in WSL) is down.
            connect_args={"connect_timeout": 5},
        )
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def sessionmaker() -> async_sessionmaker[AsyncSession]:
    get_engine()
    assert _sessionmaker is not None
    return _sessionmaker


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """A session that commits on success and rolls back on error."""
    async with sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency."""
    async with session_scope() as session:
        yield session


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
