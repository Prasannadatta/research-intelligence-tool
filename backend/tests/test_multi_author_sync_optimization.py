"""Large multi-author sync optimization: incremental sync + aggregate progress."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.db.base import Base
from app.db.models import AuthorWorkSyncState, CanonicalAuthor, ProviderAuthorRecord
from app.services.analysis.analysis_job_common import (
    format_sync_progress_stage,
    sync_progress_percent,
)
from app.services.analysis.author_work_sync import (
    STATUS_COMPLETE,
    STATUS_PARTIAL,
    AuthorWorkSyncService,
)


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setenv("OPENALEX_API_KEY", "test-key")
    monkeypatch.setenv("AUTHOR_WORK_SYNC_TTL_SECONDS", str(18 * 60 * 60))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as db:
        yield db
    await engine.dispose()


async def _seed_complete_author(session, *, index: int) -> CanonicalAuthor:
    author = CanonicalAuthor(
        id=uuid.uuid4(),
        preferred_name=f"Author {index}",
        normalized_name=f"author {index}",
        resolution_status="merged",
    )
    session.add(author)
    await session.flush()
    session.add(
        ProviderAuthorRecord(
            id=uuid.uuid4(),
            canonical_author_id=author.id,
            provider="openalex",
            provider_author_id=f"A{index:04d}",
            display_name=author.preferred_name,
            normalized_name=author.normalized_name,
            works_count=10,
        )
    )
    now = datetime.now(timezone.utc)
    session.add(
        AuthorWorkSyncState(
            id=uuid.uuid4(),
            canonical_author_id=author.id,
            provider="openalex",
            last_synced_at=now,
            last_successful_synced_at=now,
            last_attempted_at=now,
            stored_work_count=10,
            provider_work_count=10,
            status=STATUS_COMPLETE,
        )
    )
    return author


async def _seed_incomplete_author(session, *, index: int) -> CanonicalAuthor:
    author = CanonicalAuthor(
        id=uuid.uuid4(),
        preferred_name=f"New Author {index}",
        normalized_name=f"new author {index}",
        resolution_status="merged",
    )
    session.add(author)
    await session.flush()
    session.add(
        ProviderAuthorRecord(
            id=uuid.uuid4(),
            canonical_author_id=author.id,
            provider="openalex",
            provider_author_id=f"N{index:04d}",
            display_name=author.preferred_name,
            normalized_name=author.normalized_name,
            works_count=5,
        )
    )
    session.add(
        AuthorWorkSyncState(
            id=uuid.uuid4(),
            canonical_author_id=author.id,
            provider="openalex",
            last_synced_at=datetime.now(timezone.utc),
            last_attempted_at=datetime.now(timezone.utc),
            stored_work_count=2,
            provider_work_count=5,
            status=STATUS_PARTIAL,
            resume_cursor="cursor-resume",
        )
    )
    return author


def _author_rows(authors: list[CanonicalAuthor]) -> list[dict]:
    return [
        {
            "canonical_author_id": str(author.id),
            "display_name": author.preferred_name,
            "provider": "openalex",
            "provider_author_id": f"X{i}",
        }
        for i, author in enumerate(authors)
    ]


def test_sync_progress_uses_authors_ready_and_does_not_dip_on_page_reset():
    mid = sync_progress_percent(
        {
            "phase": "syncing",
            "authors_ready": 12,
            "authors_total": 20,
            "publications_processed": 50,
            "publications_total": 100,
        },
        base=10,
        span=55,
        cap=70,
    )
    reset = sync_progress_percent(
        {
            "phase": "syncing",
            "authors_ready": 12,
            "authors_total": 20,
            "publications_processed": 0,
            "publications_total": 100,
        },
        base=10,
        span=55,
        cap=70,
    )
    assert mid >= reset
    assert "12 of 20 authors ready" in format_sync_progress_stage(
        {
            "phase": "syncing",
            "authors_ready": 12,
            "authors_total": 20,
            "current_author": "Ada",
            "publications_processed": 3,
            "publications_total": 9,
        }
    )


@pytest.mark.asyncio
async def test_expanding_selection_syncs_only_new_authors(session):
    complete = [await _seed_complete_author(session, index=i) for i in range(5)]
    new_authors = [await _seed_incomplete_author(session, index=i) for i in range(15)]
    await session.commit()

    crawled: list[str] = []

    async def fake_sync_group(self, group, **kwargs):
        crawled.append(str(group.canonical_author_id))
        return {
            "canonical_author_id": str(group.canonical_author_id),
            "provider": group.provider,
            "display_name": "x",
            "stored_work_count_before": 0,
            "existing_links_repaired": 0,
            "fetched_work_count": 5,
            "new_works": 5,
            "stored_work_count_after": 5,
            "provider_work_count": 5,
            "status": STATUS_COMPLETE,
            "network_skipped": False,
            "error_message": None,
            "rate_limited": False,
            "coverage_verified": True,
            "last_synced_at": datetime.now(timezone.utc).isoformat(),
        }

    progress = []
    with patch.object(AuthorWorkSyncService, "_sync_provider_group", fake_sync_group):
        service = AuthorWorkSyncService(session)
        stats = await service.synchronize_selected_authors(
            _author_rows(complete + new_authors),
            on_progress=AsyncMock(side_effect=lambda detail: progress.append(dict(detail))),
            sync_mode="needed",
        )

    assert len(crawled) == 15
    assert set(crawled) == {str(author.id) for author in new_authors}
    skipped = [row for row in stats if row.get("network_skipped")]
    assert len(skipped) == 5
    assert any(row.get("authors_ready") == 5 for row in progress)


@pytest.mark.asyncio
async def test_removing_author_triggers_no_provider_calls(session):
    authors = [await _seed_complete_author(session, index=i) for i in range(20)]
    await session.commit()
    remaining = authors[:19]

    with patch.object(
        AuthorWorkSyncService,
        "_sync_provider_group",
        new_callable=AsyncMock,
    ) as mock_sync:
        service = AuthorWorkSyncService(session)
        fresh = await service.fresh_verified_sync_stats(_author_rows(remaining))
        assert fresh is not None
        assert len(fresh) == 19
        mock_sync.assert_not_called()

        # Even if synchronize is invoked, complete authors stay network-skipped.
        stats = await service.synchronize_selected_authors(
            _author_rows(remaining),
            sync_mode="needed",
        )
        mock_sync.assert_not_called()
        assert all(row.get("network_skipped") for row in stats)
        assert all(row.get("status") == STATUS_COMPLETE for row in stats)


@pytest.mark.asyncio
async def test_retry_incomplete_only_skips_completed_authors(session):
    complete = [await _seed_complete_author(session, index=i) for i in range(18)]
    incomplete = [await _seed_incomplete_author(session, index=i) for i in range(2)]
    # One TTL-stale previously verified author should stay skipped on Retry.
    stale = await _seed_complete_author(session, index=99)
    stale_state = (
        await session.execute(
            select(AuthorWorkSyncState).where(
                AuthorWorkSyncState.canonical_author_id == stale.id
            )
        )
    ).scalar_one()
    stale_state.last_successful_synced_at = datetime.now(timezone.utc) - timedelta(days=2)
    stale_state.last_synced_at = stale_state.last_successful_synced_at
    await session.commit()

    crawled: list[str] = []

    async def fake_sync_group(self, group, **kwargs):
        crawled.append(str(group.canonical_author_id))
        return {
            "canonical_author_id": str(group.canonical_author_id),
            "provider": group.provider,
            "display_name": "x",
            "stored_work_count_before": 2,
            "existing_links_repaired": 0,
            "fetched_work_count": 3,
            "new_works": 3,
            "stored_work_count_after": 5,
            "provider_work_count": 5,
            "status": STATUS_COMPLETE,
            "network_skipped": False,
            "error_message": None,
            "rate_limited": False,
            "coverage_verified": True,
            "last_synced_at": datetime.now(timezone.utc).isoformat(),
        }

    with patch.object(AuthorWorkSyncService, "_sync_provider_group", fake_sync_group):
        service = AuthorWorkSyncService(session)
        await service.synchronize_selected_authors(
            _author_rows(complete + incomplete + [stale]),
            sync_mode="incomplete_only",
        )

    assert set(crawled) == {str(author.id) for author in incomplete}
