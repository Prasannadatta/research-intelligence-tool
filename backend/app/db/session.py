"""Async database engine and session factory."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

_settings = get_settings()
_engine_kwargs: dict = {"pool_pre_ping": True}
if _settings.database_url.startswith("sqlite"):
    # timeout is in seconds for the pysqlite/aiosqlite busy handler.
    _engine_kwargs["connect_args"] = {
        "check_same_thread": False,
        "timeout": 30,
    }

engine = create_async_engine(_settings.database_url, **_engine_kwargs)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

if _settings.database_url.startswith("sqlite"):

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record) -> None:  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session


def _ensure_sqlite_schema_patches(sync_conn) -> None:  # noqa: ANN001
    """Patch columns create_all cannot add to existing SQLite tables.

    Alembic remains the source of truth; this only keeps local/dev DBs usable
    when a migration was not applied yet (e.g. resume_cursor).
    """
    from sqlalchemy import inspect, text

    if not str(sync_conn.engine.url).startswith("sqlite"):
        return
    inspector = inspect(sync_conn)
    if "author_work_sync_state" not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns("author_work_sync_state")}
    if "resume_cursor" not in columns:
        sync_conn.execute(
            text(
                "ALTER TABLE author_work_sync_state "
                "ADD COLUMN resume_cursor VARCHAR(512)"
            )
        )

    if "author_profiles" in inspector.get_table_names():
        profile_cols = {
            col["name"] for col in inspector.get_columns("author_profiles")
        }
        if "enrichment_meta" not in profile_cols:
            sync_conn.execute(
                text("ALTER TABLE author_profiles ADD COLUMN enrichment_meta JSON")
            )


async def init_db() -> None:
    """Create tables when using SQLite/dev without running Alembic first."""
    from app.db import models  # noqa: F401
    from app.db.base import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_sqlite_schema_patches)
