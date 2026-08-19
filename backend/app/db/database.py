"""
VyaparPro — Async SQLAlchemy Database Setup
Async engine, session factory, and dependency provider.
"""
from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any
from uuid import UUID

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, MappedColumn
from sqlalchemy.pool import NullPool, QueuePool

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""

    __abstract__ = True


# ── Engine ───────────────────────────────────────────────────────────────────

def _build_engine() -> AsyncEngine:
    if settings.DB_ENGINE == "sqlite":
        return create_async_engine(
            settings.ASYNC_DATABASE_URL,
            echo=settings.POSTGRES_ECHO,
            connect_args={"timeout": 30},
        )
    pool_class = NullPool if settings.APP_ENV == "testing" else QueuePool
    return create_async_engine(
        settings.ASYNC_DATABASE_URL,
        echo=settings.POSTGRES_ECHO,
        pool_size=settings.POSTGRES_POOL_SIZE if pool_class is QueuePool else 5,
        max_overflow=settings.POSTGRES_MAX_OVERFLOW if pool_class is QueuePool else 0,
        pool_timeout=settings.POSTGRES_POOL_TIMEOUT,
        pool_pre_ping=True,
        pool_recycle=3600,
        connect_args={
            "server_settings": {
                "application_name": settings.APP_NAME,
                "jit": "off",  # disable JIT for short OLTP queries
            }
        },
    )


engine: AsyncEngine = _build_engine()

AsyncSessionFactory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


# ── RLS helpers ──────────────────────────────────────────────────────────────

async def set_rls_context(
    session: AsyncSession,
    company_id: UUID | None = None,
    user_id: UUID | None = None,
    device_id: UUID | None = None,
) -> None:
    """Set PostgreSQL session-level config for RLS and audit triggers.
    No-op on SQLite — there's no equivalent session-scoped GUC, and the
    desktop edition is single-tenant per install so this isolation isn't
    needed there anyway."""
    if settings.DB_ENGINE != "postgresql":
        return
    stmts: list[str] = []
    if company_id:
        stmts.append(f"SET LOCAL myapp.current_company_id = '{company_id}'")
    if user_id:
        stmts.append(f"SET LOCAL myapp.current_user_id = '{user_id}'")
    if device_id:
        stmts.append(f"SET LOCAL myapp.current_device_id = '{device_id}'")
    for stmt in stmts:
        await session.execute(text(stmt))


# ── Session dependency ───────────────────────────────────────────────────────

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that yields an async DB session.
    Each request gets its own session; committed/rolled-back on exit.
    """
    async with AsyncSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ── Health check ─────────────────────────────────────────────────────────────

async def check_db_connection() -> bool:
    try:
        async with AsyncSessionFactory() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        print("Database Error:",exc)
        raise
