"""Tests for selected-author work synchronization and canonical linking."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.db.base import Base
from app.db.models import (
    AuthorWork,
    AuthorWorkSyncState,
    CanonicalAuthor,
    CanonicalWork,
    ProviderAuthorRecord,
    ProviderWorkRecord,
    WorkAuthorship,
)
from app.db.session import get_db_session
from app.main import app
from app.services.analysis.author_work_sync import AuthorWorkSyncService
from app.services.work_persistence.candidate import candidate_from_provider_result
from app.services.work_persistence.service import WorkPersistenceService

client = TestClient(app)


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setenv("OPENALEX_API_KEY", "test-key")
    monkeypatch.setenv("ARXIV_ENABLED", "false")
    monkeypatch.setenv("AUTHOR_WORK_SYNC_TTL_SECONDS", str(18 * 60 * 60))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def override_db():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_db
    try:
        yield factory
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        await engine.dispose()


async def _seed_author(
    session: AsyncSession,
    *,
    name: str,
    openalex_id: str,
) -> CanonicalAuthor:
    author = CanonicalAuthor(
        id=uuid.uuid4(),
        preferred_name=name,
        normalized_name=name.lower(),
        resolution_status="merged",
    )
    session.add(author)
    await session.flush()
    session.add(
        ProviderAuthorRecord(
            id=uuid.uuid4(),
            canonical_author_id=author.id,
            provider="openalex",
            provider_author_id=openalex_id,
            display_name=name,
            normalized_name=name.lower(),
            works_count=1,
        )
    )
    return author


async def _provider_record(
    session: AsyncSession,
    author: CanonicalAuthor,
) -> ProviderAuthorRecord:
    return (
        await session.execute(
            select(ProviderAuthorRecord).where(
                ProviderAuthorRecord.canonical_author_id == author.id
            )
        )
    ).scalar_one()


async def _seed_stored_work(
    session: AsyncSession,
    *,
    title: str,
    provider_work_id: str,
    provider_author_id: str,
    display_name: str,
    canonical_author_id: uuid.UUID | None = None,
) -> CanonicalWork:
    work = CanonicalWork(
        id=uuid.uuid4(),
        title=title,
        normalized_title=title.lower(),
        publication_year=2024,
        normalized_first_author=display_name.lower(),
    )
    session.add(work)
    await session.flush()
    session.add(
        ProviderWorkRecord(
            id=uuid.uuid4(),
            canonical_work_id=work.id,
            provider="openalex",
            provider_work_id=provider_work_id,
            raw_metadata={"title": title, "publication_year": 2024},
        )
    )
    session.add(
        WorkAuthorship(
            id=uuid.uuid4(),
            canonical_work_id=work.id,
            provider="openalex",
            provider_author_id=provider_author_id,
            canonical_author_id=canonical_author_id,
            display_name=display_name,
            author_position=0,
            institutions=[],
            institution_ids=[],
            countries=[],
        )
    )
    return work


def _author_payload(author: CanonicalAuthor) -> dict:
    return {
        "canonical_author_id": str(author.id),
        "display_name": author.preferred_name,
    }


def _work_row(work_id: str, title: str, authors: list[tuple[str, str]]) -> dict:
    return {
        "result_id": f"openalex:{work_id}",
        "result_type": "work",
        "openalex_id": work_id,
        "source_id": work_id,
        "source": "openalex",
        "title": title,
        "publication_year": 2024,
        "primary_source": "Journal",
        "cited_by_count": 1,
        "authors": [
            {
                "id": author_id,
                "name": name,
                "display_name": name,
                "author_position": index,
                "provider_ids": {"openalex": [author_id], "orcid": [], "arxiv": []},
                "institutions": [],
                "institution_ids": [],
                "countries": [],
            }
            for index, (author_id, name) in enumerate(authors)
        ],
    }


@pytest.mark.asyncio
async def test_historical_authorship_link_repair_updates_author_works(session_factory):
    async with session_factory() as session:
        author = await _seed_author(session, name="Author A", openalex_id="A1")
        await _seed_stored_work(
            session,
            title="Stored Paper",
            provider_work_id="W1",
            provider_author_id="A1",
            display_name="Author A",
        )
        await session.commit()

        with patch(
            "app.services.analysis.author_work_sync.search_works_by_author_ids",
            new_callable=AsyncMock,
        ) as mock_fetch:
            mock_fetch.return_value = {
                "results": [],
                "has_more": False,
                "next_cursor": None,
                "count": 1,
            }
            stats = await AuthorWorkSyncService(session).synchronize_selected_authors(
                [_author_payload(author)]
            )

        linked = (
            await session.execute(
                select(WorkAuthorship).where(
                    WorkAuthorship.canonical_author_id == author.id
                )
            )
        ).scalar_one()
        author_work_count = (
            await session.execute(select(func.count(AuthorWork.id)))
        ).scalar_one()

    assert linked.provider_author_id == "A1"
    assert author_work_count == 1
    assert stats[0]["existing_links_repaired"] == 1
    assert stats[0]["stored_work_count_after"] == 1
    assert stats[0]["status"] == "complete"


@pytest.mark.asyncio
async def test_repair_links_by_provider_id_not_name(session_factory):
    async with session_factory() as session:
        author = await _seed_author(session, name="Shared Name", openalex_id="A1")
        await _seed_stored_work(
            session,
            title="Wrong Provider Author",
            provider_work_id="W2",
            provider_author_id="A2",
            display_name="Shared Name",
        )
        await session.commit()

        with patch(
            "app.services.analysis.author_work_sync.search_works_by_author_ids",
            new_callable=AsyncMock,
        ) as mock_fetch:
            mock_fetch.return_value = {
                "results": [],
                "has_more": False,
                "next_cursor": None,
                "count": 0,
            }
            await AuthorWorkSyncService(session).synchronize_selected_authors(
                [_author_payload(author)]
            )

        count = (
            await session.execute(
                select(func.count(WorkAuthorship.id)).where(
                    WorkAuthorship.canonical_author_id == author.id
                )
            )
        ).scalar_one()

    assert count == 0


@pytest.mark.asyncio
async def test_future_persistence_links_known_authors_and_coauthors(session_factory):
    async with session_factory() as session:
        author_a = await _seed_author(session, name="Author A", openalex_id="A1")
        author_b = await _seed_author(session, name="Author B", openalex_id="A2")
        candidate = candidate_from_provider_result(
            _work_row("W3", "Future Paper", [("A1", "Author A"), ("A2", "Author B")]),
            provider="openalex",
        )

        await WorkPersistenceService(session).resolve_candidate(candidate)
        await session.commit()

        linked_ids = {
            str(row.canonical_author_id)
            for row in (
                await session.execute(select(WorkAuthorship))
            ).scalars().all()
        }
        author_work_count = (
            await session.execute(select(func.count(AuthorWork.id)))
        ).scalar_one()

    assert linked_ids == {str(author_a.id), str(author_b.id)}
    assert author_work_count == 2


@pytest.mark.asyncio
async def test_sync_repairs_existing_provider_work_missing_authoritative_authorship(
    session_factory,
):
    async with session_factory() as session:
        author = await _seed_author(session, name="Author A", openalex_id="A1")
        work = CanonicalWork(
            id=uuid.uuid4(),
            title="Existing Provider Paper",
            normalized_title="existing provider paper",
            publication_year=2024,
            normalized_first_author="author a",
        )
        session.add(work)
        await session.flush()
        session.add(
            ProviderWorkRecord(
                id=uuid.uuid4(),
                canonical_work_id=work.id,
                provider="openalex",
                provider_work_id="W-existing",
                raw_metadata={"title": "Existing Provider Paper", "publication_year": 2024},
            )
        )
        await session.commit()

        with patch(
            "app.services.analysis.author_work_sync.search_works_by_author_ids",
            new_callable=AsyncMock,
        ) as mock_fetch:
            mock_fetch.return_value = {
                "results": [
                    _work_row(
                        "W-existing",
                        "Existing Provider Paper",
                        [("A1", "Author A")],
                    )
                ],
                "has_more": False,
                "next_cursor": None,
                "count": 1,
            }
            stats = await AuthorWorkSyncService(session).synchronize_selected_authors(
                [_author_payload(author)]
            )

        linked_count = (
            await session.execute(
                select(func.count(WorkAuthorship.id)).where(
                    WorkAuthorship.canonical_author_id == author.id
                )
            )
        ).scalar_one()

    assert stats[0]["new_works"] == 0
    assert linked_count == 1


@pytest.mark.asyncio
async def test_repeated_sync_is_idempotent_and_fresh_state_skips_provider_fetch(
    session_factory,
):
    async with session_factory() as session:
        author = await _seed_author(session, name="Author A", openalex_id="A1")
        with patch(
            "app.services.analysis.author_work_sync.search_works_by_author_ids",
            new_callable=AsyncMock,
        ) as mock_fetch:
            mock_fetch.return_value = {
                "results": [_work_row("W4", "Synced Paper", [("A1", "Author A")])],
                "has_more": False,
                "next_cursor": None,
                "count": 1,
            }

            first = await AuthorWorkSyncService(session).synchronize_selected_authors(
                [_author_payload(author)]
            )
            second = await AuthorWorkSyncService(session).synchronize_selected_authors(
                [_author_payload(author)]
            )

        work_count = (
            await session.execute(
                select(func.count(func.distinct(WorkAuthorship.canonical_work_id)))
            )
        ).scalar_one()

    assert mock_fetch.await_count == 1
    assert first[0]["fetched_work_count"] == 1
    assert second[0]["status"] == "complete"
    assert second[0]["network_skipped"] is True
    assert work_count == 1


@pytest.mark.asyncio
async def test_sync_fetches_all_provider_ids_before_marking_provider_fresh(
    session_factory,
):
    async with session_factory() as session:
        author = await _seed_author(session, name="Author A", openalex_id="A1")
        session.add(
            ProviderAuthorRecord(
                id=uuid.uuid4(),
                canonical_author_id=author.id,
                provider="openalex",
                provider_author_id="A1b",
                display_name="Author A",
                normalized_name="author a",
                works_count=1,
            )
        )
        await session.commit()

        async def fake_fetch(*, author_id_groups, **_kwargs):
            ids = author_id_groups[0]
            assert set(ids) == {"A1", "A1b"}
            return {
                "results": [
                    _work_row("W-A1", "Paper A1", [("A1", "Author A")]),
                    _work_row("W-A1b", "Paper A1b", [("A1b", "Author A")]),
                ],
                "has_more": False,
                "next_cursor": None,
                "count": 2,
            }

        with patch(
            "app.services.analysis.author_work_sync.search_works_by_author_ids",
            side_effect=fake_fetch,
        ) as mock_fetch:
            first = await AuthorWorkSyncService(session).synchronize_selected_authors(
                [_author_payload(author)]
            )
            second = await AuthorWorkSyncService(session).synchronize_selected_authors(
                [_author_payload(author)]
            )

        work_count = (
            await session.execute(
                select(func.count(func.distinct(WorkAuthorship.canonical_work_id))).where(
                    WorkAuthorship.canonical_author_id == author.id
                )
            )
        ).scalar_one()

    assert mock_fetch.await_count == 1
    assert first[0]["status"] == "complete"
    assert first[0]["coverage_verified"] is True
    assert second[0]["status"] == "complete"
    assert second[0]["network_skipped"] is True
    assert work_count == 2


@pytest.mark.asyncio
async def test_stale_sync_refetches_provider(session_factory):
    async with session_factory() as session:
        author = await _seed_author(session, name="Author A", openalex_id="A1")
        session.add(
            AuthorWorkSyncState(
                id=uuid.uuid4(),
                canonical_author_id=author.id,
                provider="openalex",
                last_synced_at=datetime.now(timezone.utc) - timedelta(days=2),
                last_successful_synced_at=datetime.now(timezone.utc) - timedelta(days=2),
                last_attempted_at=datetime.now(timezone.utc) - timedelta(days=2),
                stored_work_count=0,
                provider_work_count=None,
                status="complete",
            )
        )
        await session.commit()

        with patch(
            "app.services.analysis.author_work_sync.search_works_by_author_ids",
            new_callable=AsyncMock,
        ) as mock_fetch:
            mock_fetch.return_value = {
                "results": [],
                "has_more": False,
                "next_cursor": None,
                "count": 0,
            }
            await AuthorWorkSyncService(session).synchronize_selected_authors(
                [_author_payload(author)]
            )

    assert mock_fetch.await_count == 1


@pytest.mark.asyncio
async def test_provider_fetch_occurs_outside_write_transaction(session_factory):
    async with session_factory() as session:
        author = await _seed_author(session, name="Author A", openalex_id="A1")
        await session.commit()

        async def fake_fetch(**_kwargs):
            assert session.in_transaction() is False
            return {
                "results": [],
                "has_more": False,
                "next_cursor": None,
                "count": 0,
            }

        with patch(
            "app.services.analysis.author_work_sync.search_works_by_author_ids",
            side_effect=fake_fetch,
        ):
            await AuthorWorkSyncService(session).synchronize_selected_authors(
                [_author_payload(author)]
            )


@pytest.mark.asyncio
async def test_simultaneous_same_author_sync_is_deduplicated(session_factory):
    async with session_factory() as setup_session:
        author = await _seed_author(setup_session, name="Author A", openalex_id="A1")
        await setup_session.commit()

    async def run_sync():
        async with session_factory() as session:
            service = AuthorWorkSyncService(session)
            return await service.synchronize_selected_authors([_author_payload(author)])

    async def fake_fetch(**_kwargs):
        await asyncio.sleep(0.05)
        return {
            "results": [_work_row("W5", "Concurrent Paper", [("A1", "Author A")])],
            "has_more": False,
            "next_cursor": None,
            "count": 1,
        }

    with patch(
        "app.services.analysis.author_work_sync.search_works_by_author_ids",
        side_effect=fake_fetch,
    ) as mock_fetch:
        await asyncio.gather(run_sync(), run_sync())

    assert mock_fetch.await_count == 1


@pytest.mark.asyncio
async def test_provider_failure_falls_back_to_repaired_stored_coverage(session_factory):
    async with session_factory() as session:
        author = await _seed_author(session, name="Author A", openalex_id="A1")
        await _seed_stored_work(
            session,
            title="Stored Paper",
            provider_work_id="W6",
            provider_author_id="A1",
            display_name="Author A",
        )
        await session.commit()

        with patch(
            "app.services.analysis.author_work_sync.search_works_by_author_ids",
            new_callable=AsyncMock,
        ) as mock_fetch:
            mock_fetch.side_effect = RuntimeError("unexpected")
            stats = await AuthorWorkSyncService(session).synchronize_selected_authors(
                [_author_payload(author)]
            )

        count = (
            await session.execute(
                select(func.count(WorkAuthorship.id)).where(
                    WorkAuthorship.canonical_author_id == author.id
                )
            )
        ).scalar_one()

    assert stats[0]["status"] == "partial"
    assert count == 1

def test_pairwise_publications_outside_abc_available_in_insights_after_sync(session_factory):
    async def seed():
        async with session_factory() as session:
            a = await _seed_author(session, name="Author A", openalex_id="A1")
            b = await _seed_author(session, name="Author B", openalex_id="A2")
            c = await _seed_author(session, name="Author C", openalex_id="A3")
            await session.commit()
            return a, b, c

    author_a, author_b, author_c = asyncio.run(seed())

    responses = {
        "A1": [
            _work_row("WAB", "AB", [("A1", "Author A"), ("A2", "Author B")]),
            _work_row("WAC", "AC", [("A1", "Author A"), ("A3", "Author C")]),
            _work_row(
                "WABC",
                "ABC",
                [("A1", "Author A"), ("A2", "Author B"), ("A3", "Author C")],
            ),
        ],
        "A2": [
            _work_row("WAB", "AB", [("A1", "Author A"), ("A2", "Author B")]),
            _work_row("WBC", "BC", [("A2", "Author B"), ("A3", "Author C")]),
            _work_row(
                "WABC",
                "ABC",
                [("A1", "Author A"), ("A2", "Author B"), ("A3", "Author C")],
            ),
        ],
        "A3": [
            _work_row("WAC", "AC", [("A1", "Author A"), ("A3", "Author C")]),
            _work_row("WBC", "BC", [("A2", "Author B"), ("A3", "Author C")]),
            _work_row(
                "WABC",
                "ABC",
                [("A1", "Author A"), ("A2", "Author B"), ("A3", "Author C")],
            ),
        ],
    }

    async def fake_fetch(*, author_id_groups, **_kwargs):
        author_id = author_id_groups[0][0]
        rows = responses[author_id]
        return {
            "results": rows,
            "has_more": False,
            "next_cursor": None,
            "count": len(rows),
        }

    with patch(
        "app.services.analysis.author_work_sync.search_works_by_author_ids",
        side_effect=fake_fetch,
    ) as mock_fetch:
        async def run_sync():
            async with session_factory() as session:
                await AuthorWorkSyncService(session).synchronize_selected_authors(
                    [
                        _author_payload(author_a),
                        _author_payload(author_b),
                        _author_payload(author_c),
                    ]
                )

        asyncio.run(run_sync())
        fetch_count_after_sync = mock_fetch.await_count
        response = client.post(
            "/api/analysis/authors/insights",
            json={
                "authors": [
                    _author_payload(author_a),
                    _author_payload(author_b),
                    _author_payload(author_c),
                ]
            },
        )

    assert response.status_code == 200
    assert mock_fetch.await_count == fetch_count_after_sync
    payload = response.json()
    combinations = {row["label"]: row["publication_count"] for row in payload["combinations"]}
    assert payload["metrics"]["total_unique_publications"] == 4
    assert payload["metrics"]["all_selected_author_publications"] == 1
    assert combinations == {
        "Author A + Author B": 2,
        "Author A + Author C": 2,
        "Author B + Author C": 2,
        "Author A + Author B + Author C": 1,
    }


@pytest.mark.asyncio
async def test_sync_timeout_skips_remaining_author_groups(session_factory):
    async with session_factory() as session:
        author_a = await _seed_author(session, name="Author A", openalex_id="A1")
        author_b = await _seed_author(session, name="Author B", openalex_id="A2")
        await session.commit()

        with patch(
            "app.services.analysis.author_work_sync.search_works_by_author_ids",
            new_callable=AsyncMock,
        ) as mock_fetch:
            mock_fetch.return_value = {
                "results": [_work_row("W1", "Paper", [("A1", "Author A")])],
                "has_more": False,
                "next_cursor": None,
                "count": 1,
            }
            stats = await AuthorWorkSyncService(session).synchronize_selected_authors(
                [_author_payload(author_a), _author_payload(author_b)],
                timeout_seconds=0,
            )

    assert mock_fetch.await_count == 0
    assert len(stats) == 2
    assert {row["status"] for row in stats} == {"partial"}


@pytest.mark.asyncio
async def test_undercounted_crawl_is_not_marked_complete(session_factory):
    async with session_factory() as session:
        author = await _seed_author(session, name="Author A", openalex_id="A1")
        await session.commit()

        with patch(
            "app.services.analysis.author_work_sync.search_works_by_author_ids",
            new_callable=AsyncMock,
        ) as mock_fetch:
            mock_fetch.return_value = {
                "results": [_work_row("W1", "Only One", [("A1", "Author A")])],
                "has_more": False,
                "next_cursor": None,
                "count": 5,
            }
            stats = await AuthorWorkSyncService(session).synchronize_selected_authors(
                [_author_payload(author)]
            )

        state = (
            await session.execute(
                select(AuthorWorkSyncState).where(
                    AuthorWorkSyncState.canonical_author_id == author.id
                )
            )
        ).scalar_one()

    assert stats[0]["status"] == "partial"
    assert stats[0]["coverage_verified"] is False
    assert "Linked 1" in (stats[0]["error_message"] or "")
    assert state.status == "partial"
    assert state.provider_work_count == 5


@pytest.mark.asyncio
async def test_missing_provider_total_cannot_be_marked_complete(session_factory):
    async with session_factory() as session:
        author = await _seed_author(session, name="Author A", openalex_id="A1")
        record = await _provider_record(session, author)
        record.works_count = None
        await session.commit()

        with patch(
            "app.services.analysis.author_work_sync.search_works_by_author_ids",
            new_callable=AsyncMock,
        ) as mock_fetch:
            mock_fetch.return_value = {
                "results": [_work_row("W1", "Paper", [("A1", "Author A")])],
                "has_more": False,
                "next_cursor": None,
                "count": None,
            }
            stats = await AuthorWorkSyncService(session).synchronize_selected_authors(
                [_author_payload(author)]
            )

    assert stats[0]["status"] == "partial"
    assert "cannot be verified" in (stats[0]["error_message"] or "").lower()


@pytest.mark.asyncio
async def test_rate_limit_preserves_prior_complete_data_and_resume_cursor(session_factory):
    async with session_factory() as session:
        author = await _seed_author(session, name="Author A", openalex_id="A1")
        await session.commit()

        with patch(
            "app.services.analysis.author_work_sync.search_works_by_author_ids",
            new_callable=AsyncMock,
        ) as mock_fetch:
            mock_fetch.return_value = {
                "results": [_work_row("W1", "Paper", [("A1", "Author A")])],
                "has_more": False,
                "next_cursor": None,
                "count": 1,
            }
            first = await AuthorWorkSyncService(session).synchronize_selected_authors(
                [_author_payload(author)]
            )
            assert first[0]["status"] == "complete"

            from app.integrations.openalex.client import OpenAlexApiError

            mock_fetch.side_effect = OpenAlexApiError(
                "OpenAlex rate limit reached.",
                status_code=429,
            )
            # Force refresh by making coverage stale.
            state = (
                await session.execute(
                    select(AuthorWorkSyncState).where(
                        AuthorWorkSyncState.canonical_author_id == author.id
                    )
                )
            ).scalar_one()
            state.last_successful_synced_at = datetime.now(timezone.utc) - timedelta(days=2)
            state.last_synced_at = state.last_successful_synced_at
            await session.commit()

            second = await AuthorWorkSyncService(session).synchronize_selected_authors(
                [_author_payload(author)]
            )

        count = (
            await session.execute(
                select(func.count(func.distinct(WorkAuthorship.canonical_work_id))).where(
                    WorkAuthorship.canonical_author_id == author.id
                )
            )
        ).scalar_one()
        state = (
            await session.execute(
                select(AuthorWorkSyncState).where(
                    AuthorWorkSyncState.canonical_author_id == author.id
                )
            )
        ).scalar_one()

    assert second[0]["status"] == "partial"
    assert second[0]["rate_limited"] is True
    assert count == 1
    assert state.last_successful_synced_at is not None
    assert state.resume_cursor == "*"


@pytest.mark.asyncio
async def test_pagination_resume_continues_from_saved_cursor(session_factory):
    async with session_factory() as session:
        author = await _seed_author(session, name="Author A", openalex_id="A1")
        await session.commit()

        pages = [
            {
                "results": [_work_row("W1", "One", [("A1", "Author A")])],
                "has_more": True,
                "next_cursor": "page-2",
                "count": 2,
            },
            {
                "results": [_work_row("W2", "Two", [("A1", "Author A")])],
                "has_more": False,
                "next_cursor": None,
                "count": 2,
            },
        ]

        with patch(
            "app.services.analysis.author_work_sync.search_works_by_author_ids",
            new_callable=AsyncMock,
        ) as mock_fetch:
            from app.integrations.openalex.client import OpenAlexApiError

            mock_fetch.side_effect = [
                pages[0],
                OpenAlexApiError("OpenAlex rate limit reached.", status_code=429),
            ]
            partial = await AuthorWorkSyncService(session).synchronize_selected_authors(
                [_author_payload(author)]
            )
            assert partial[0]["status"] == "partial"
            assert partial[0]["resume_cursor"] == "page-2"

            mock_fetch.side_effect = [pages[1]]
            done = await AuthorWorkSyncService(session).synchronize_selected_authors(
                [_author_payload(author)]
            )

        work_count = (
            await session.execute(
                select(func.count(func.distinct(WorkAuthorship.canonical_work_id))).where(
                    WorkAuthorship.canonical_author_id == author.id
                )
            )
        ).scalar_one()
        state = (
            await session.execute(
                select(AuthorWorkSyncState).where(
                    AuthorWorkSyncState.canonical_author_id == author.id
                )
            )
        ).scalar_one()

    assert mock_fetch.await_count == 3
    resume_call = mock_fetch.await_args_list[2]
    assert resume_call.kwargs["cursor"] == "page-2"
    assert done[0]["status"] == "complete"
    assert done[0]["coverage_verified"] is True
    assert work_count == 2
    assert state.resume_cursor is None
    assert state.status == "complete"


@pytest.mark.asyncio
async def test_empty_page_with_continuation_cursor_is_partial(session_factory):
    async with session_factory() as session:
        author = await _seed_author(session, name="Author A", openalex_id="A1")
        await session.commit()

        with patch(
            "app.services.analysis.author_work_sync.search_works_by_author_ids",
            new_callable=AsyncMock,
        ) as mock_fetch:
            mock_fetch.return_value = {
                "results": [],
                "has_more": False,
                "next_cursor": "ghost-cursor",
                "count": 3,
            }
            stats = await AuthorWorkSyncService(session).synchronize_selected_authors(
                [_author_payload(author)]
            )

    assert stats[0]["status"] == "partial"
    assert "empty page" in (stats[0]["error_message"] or "").lower()


@pytest.mark.asyncio
async def test_unverified_complete_within_ttl_is_refetched(session_factory):
    """Legacy complete rows without provider_work_count must not skip network."""
    async with session_factory() as session:
        author = await _seed_author(session, name="Author A", openalex_id="A1")
        session.add(
            AuthorWorkSyncState(
                id=uuid.uuid4(),
                canonical_author_id=author.id,
                provider="openalex",
                last_synced_at=datetime.now(timezone.utc),
                last_successful_synced_at=datetime.now(timezone.utc),
                last_attempted_at=datetime.now(timezone.utc),
                stored_work_count=1,
                provider_work_count=None,
                status="complete",
            )
        )
        await session.commit()

        with patch(
            "app.services.analysis.author_work_sync.search_works_by_author_ids",
            new_callable=AsyncMock,
        ) as mock_fetch:
            mock_fetch.return_value = {
                "results": [_work_row("W1", "Paper", [("A1", "Author A")])],
                "has_more": False,
                "next_cursor": None,
                "count": 1,
            }
            stats = await AuthorWorkSyncService(session).synchronize_selected_authors(
                [_author_payload(author)]
            )

    assert mock_fetch.await_count == 1
    assert stats[0]["network_skipped"] is False
    assert stats[0]["status"] == "complete"


@pytest.mark.asyncio
async def test_no_provider_identity_fails_instead_of_empty_complete(session_factory):
    async with session_factory() as session:
        author = CanonicalAuthor(
            id=uuid.uuid4(),
            preferred_name="Orphan",
            normalized_name="orphan",
            resolution_status="merged",
        )
        session.add(author)
        await session.commit()

        stats = await AuthorWorkSyncService(session).synchronize_selected_authors(
            [_author_payload(author)]
        )

    assert len(stats) == 1
    assert stats[0]["status"] == "failed"
    assert stats[0]["coverage_verified"] is False
    assert "No OpenAlex/arXiv provider identity" in (stats[0]["error_message"] or "")


@pytest.mark.asyncio
async def test_completeness_requires_linked_authorship_not_just_crawl_ids(session_factory):
    async with session_factory() as session:
        author = await _seed_author(session, name="Author A", openalex_id="A1")
        await session.commit()

        # Work payload omits the selected author from authorships metadata.
        row = _work_row("W-missing-author", "Missing Author Meta", [("A999", "Other")])
        row["authors"] = [
            {
                "id": "A999",
                "name": "Other",
                "display_name": "Other",
                "author_position": 0,
                "provider_ids": {"openalex": ["A999"], "orcid": [], "arxiv": []},
                "institutions": [],
                "institution_ids": [],
                "countries": [],
            }
        ]

        with patch(
            "app.services.analysis.author_work_sync.search_works_by_author_ids",
            new_callable=AsyncMock,
            return_value={
                "results": [row],
                "has_more": False,
                "next_cursor": None,
                "count": 1,
            },
        ):
            stats = await AuthorWorkSyncService(session).synchronize_selected_authors(
                [_author_payload(author)]
            )

        linked = (
            await session.execute(
                select(func.count(WorkAuthorship.id)).where(
                    WorkAuthorship.canonical_author_id == author.id
                )
            )
        ).scalar_one()

    assert linked == 1  # selected authorship injected
    assert stats[0]["status"] == "complete"
    assert stats[0]["coverage_verified"] is True


@pytest.mark.asyncio
async def test_sync_refresh_links_known_coauthors_for_intersection(session_factory):
    async with session_factory() as session:
        author_a = await _seed_author(session, name="Author A", openalex_id="A1")
        author_b = await _seed_author(session, name="Author B", openalex_id="A2")
        await session.commit()

        with patch(
            "app.services.analysis.author_work_sync.search_works_by_author_ids",
            new_callable=AsyncMock,
        ) as mock_fetch:
            mock_fetch.side_effect = [
                {
                    "results": [
                        _work_row(
                            "W-AB",
                            "Shared",
                            [("A1", "Author A"), ("A2", "Author B")],
                        )
                    ],
                    "has_more": False,
                    "next_cursor": None,
                    "count": 1,
                },
                {
                    "results": [],
                    "has_more": False,
                    "next_cursor": None,
                    "count": 0,
                },
            ]
            await AuthorWorkSyncService(session).synchronize_selected_authors(
                [_author_payload(author_a)]
            )
            # B has empty crawl but should already be linked from A's replace_work_authorships.
            await AuthorWorkSyncService(session).synchronize_selected_authors(
                [_author_payload(author_b)]
            )

        linked_b = (
            await session.execute(
                select(func.count(WorkAuthorship.id)).where(
                    WorkAuthorship.canonical_author_id == author_b.id,
                    WorkAuthorship.canonical_work_id.in_(
                        select(WorkAuthorship.canonical_work_id).where(
                            WorkAuthorship.canonical_author_id == author_a.id
                        )
                    ),
                )
            )
        ).scalar_one()

    assert linked_b == 1


@pytest.mark.asyncio
async def test_timeout_before_start_preserves_resume_cursor(session_factory):
    async with session_factory() as session:
        author_a = await _seed_author(session, name="Author A", openalex_id="A1")
        author_b = await _seed_author(session, name="Author B", openalex_id="A2")
        session.add(
            AuthorWorkSyncState(
                id=uuid.uuid4(),
                canonical_author_id=author_b.id,
                provider="openalex",
                last_synced_at=None,
                last_successful_synced_at=None,
                last_attempted_at=datetime.now(timezone.utc),
                stored_work_count=1,
                provider_work_count=3,
                status="partial",
                resume_cursor="keep-me",
                error_message="mid-crawl",
            )
        )
        await session.commit()

        with patch(
            "app.services.analysis.author_work_sync.search_works_by_author_ids",
            new_callable=AsyncMock,
        ) as mock_fetch:
            mock_fetch.return_value = {
                "results": [_work_row("W1", "Paper", [("A1", "Author A")])],
                "has_more": False,
                "next_cursor": None,
                "count": 1,
            }
            stats = await AuthorWorkSyncService(session).synchronize_selected_authors(
                [_author_payload(author_a), _author_payload(author_b)],
                timeout_seconds=0,
            )

        state_b = (
            await session.execute(
                select(AuthorWorkSyncState).where(
                    AuthorWorkSyncState.canonical_author_id == author_b.id
                )
            )
        ).scalar_one()

    assert all(row["status"] == "partial" for row in stats)
    assert state_b.resume_cursor == "keep-me"


def test_blocking_sync_problems_requires_openalex_not_arxiv_enrichment():
    from app.services.analysis.sync_job_errors import _blocking_sync_problems

    assert _blocking_sync_problems([])  # empty is blocking
    assert not _blocking_sync_problems(
        [
            {
                "canonical_author_id": "a1",
                "provider": "openalex",
                "status": "complete",
                "coverage_verified": True,
            },
            {
                "canonical_author_id": "a1",
                "provider": "arxiv",
                "status": "partial",
                "coverage_verified": False,
                "error_message": "unverified",
            },
        ]
    )
    problems = _blocking_sync_problems(
        [
            {
                "canonical_author_id": "a1",
                "provider": "arxiv",
                "status": "partial",
                "coverage_verified": False,
                "display_name": "Only Arxiv",
            }
        ]
    )
    assert problems
    assert "OpenAlex" in (problems[0].get("error_message") or "")
