"""OpenAlex-selected and ORCID-selected Analyze paths share the same OA corpus."""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import CanonicalAuthor, ProviderAuthorRecord
from app.services.analysis.author_publications import _resolve_author


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as db:
        yield db
    await engine.dispose()


@pytest.mark.asyncio
async def test_orcid_and_openalex_selection_resolve_same_primary_oa_ids(session):
    canonical = CanonicalAuthor(
        id=uuid.uuid4(),
        preferred_name="Shared Author",
        normalized_name="shared author",
        resolution_status="merged",
    )
    session.add(canonical)
    await session.flush()
    session.add(
        ProviderAuthorRecord(
            id=uuid.uuid4(),
            canonical_author_id=canonical.id,
            provider="openalex",
            provider_author_id="A100",
            display_name="Shared Author",
            normalized_name="shared author",
            works_count=50,
            orcid="0000-0001-1111-1111",
        )
    )
    session.add(
        ProviderAuthorRecord(
            id=uuid.uuid4(),
            canonical_author_id=canonical.id,
            provider="openalex",
            provider_author_id="A200",
            display_name="Shared Author",
            normalized_name="shared author",
            works_count=5,
            orcid="0000-0001-1111-1111",
        )
    )
    session.add(
        ProviderAuthorRecord(
            id=uuid.uuid4(),
            canonical_author_id=canonical.id,
            provider="orcid",
            provider_author_id="0000-0001-1111-1111",
            display_name="Shared Author",
            normalized_name="shared author",
            orcid="0000-0001-1111-1111",
        )
    )
    await session.commit()

    via_oa = await _resolve_author(
        session,
        {
            "canonical_author_id": str(canonical.id),
            "display_name": "Shared Author",
            "provider": "openalex",
            "provider_author_id": "A100",
        },
    )
    via_orcid = await _resolve_author(
        session,
        {
            "canonical_author_id": str(canonical.id),
            "display_name": "Shared Author",
            "provider": "orcid",
            "provider_author_id": "0000-0001-1111-1111",
        },
    )

    assert via_oa.openalex_ids == ["A100"]
    assert via_orcid.openalex_ids == ["A100"]
