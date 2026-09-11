"""Ensure create_all + local patches keep analysis sync schema usable."""

from __future__ import annotations

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.base import Base
from app.db.session import _ensure_sqlite_schema_patches


@pytest.mark.asyncio
async def test_ensure_sqlite_schema_patches_adds_resume_cursor():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Simulate a pre-016 database missing resume_cursor.
        await conn.execute(text("ALTER TABLE author_work_sync_state DROP COLUMN resume_cursor"))

        def _missing(sync_conn):
            cols = {
                col["name"]
                for col in inspect(sync_conn).get_columns("author_work_sync_state")
            }
            assert "resume_cursor" not in cols

        await conn.run_sync(_missing)
        await conn.run_sync(_ensure_sqlite_schema_patches)

        def _present(sync_conn):
            cols = {
                col["name"]
                for col in inspect(sync_conn).get_columns("author_work_sync_state")
            }
            assert "resume_cursor" in cols

        await conn.run_sync(_present)
    await engine.dispose()
