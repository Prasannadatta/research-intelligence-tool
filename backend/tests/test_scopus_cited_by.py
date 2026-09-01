"""Scopus cited-by ID resolution, REF pagination, cache, and persistence."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.db.base import Base
from app.db.models import (
    CanonicalWork,
    ScopusCitationLink,
    ScopusCitingWork,
)
from app.integrations.elsevier.cited_by import (
    doi_search_query,
    normalize_affiliations,
    parse_citing_entry,
    parse_scopus_ids_from_abstract,
    ref_query,
    resolve_scopus_ids_for_doi,
)
from app.integrations.elsevier.client import ElsevierClient
from app.integrations import rate_limited_http
from app.services.scopus_cited_by.service import (
    ScopusCitedByService,
    http_ran_during_transaction,
    reset_http_during_transaction_flag,
)
from app.services.work_persistence.normalization import normalize_doi


SOURCE_SCOPUS_ID = "85111111111"
CITING_A = "85900000001"
CITING_B = "85900000002"


def _response(status: int, payload: dict, url: str = "https://api.elsevier.com/") -> httpx.Response:
    return httpx.Response(status, json=payload, request=httpx.Request("GET", url))


def _meta_payload(scopus_id: str = SOURCE_SCOPUS_ID, citedby_count: str = "2") -> dict:
    return {
        "abstracts-retrieval-response": {
            "coredata": {
                "eid": f"2-s2.0-{scopus_id}",
                "dc:identifier": f"SCOPUS_ID:{scopus_id}",
                "citedby-count": citedby_count,
            }
        }
    }


def _citing_entry(
    scopus_id: str,
    *,
    doi: str | None = None,
    title: str = "Citing paper",
    affiliations: list[dict] | None = None,
) -> dict:
    entry = {
        "dc:identifier": f"SCOPUS_ID:{scopus_id}",
        "eid": f"2-s2.0-{scopus_id}",
        "dc:title": title,
        "prism:coverDate": "2024-03-01",
        "prism:publicationName": "Nature Physics",
        "affiliation": affiliations
        or [
            {"affilname": "UC Berkeley", "affiliation-country": "United States"},
            {"affilname": "UC Berkeley", "affiliation-country": "United States"},
            {"affilname": "LBNL", "affiliation-country": "United States"},
        ],
    }
    if doi:
        entry["prism:doi"] = doi
    return entry


def _search_page(*, total: int, start: int, entries: list[dict]) -> dict:
    return {
        "search-results": {
            "opensearch:totalResults": str(total),
            "opensearch:startIndex": str(start),
            "opensearch:itemsPerPage": str(len(entries)),
            "entry": entries,
        }
    }


@pytest.fixture
def elsevier_key(monkeypatch):
    monkeypatch.setenv("ELSEVIER_API_KEY", "test-elsevier-key")
    monkeypatch.delenv("ELSEVIER_INST_TOKEN", raising=False)
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
    try:
        yield factory
    finally:
        await engine.dispose()


async def _seed_canonical(session: AsyncSession, *, doi: str, title: str = "Source paper") -> CanonicalWork:
    work = CanonicalWork(
        id=uuid.uuid4(),
        title=title,
        normalized_title=title.lower(),
        publication_year=2020,
        doi=doi,
    )
    session.add(work)
    await session.commit()
    return work


class RecordingElsevier:
    def __init__(self, handler) -> None:
        self.handler = handler
        self.calls: list[dict] = []

    async def __call__(self, provider, url, *, params=None, headers=None, timeout=None):
        captured = dict(params or {})
        self.calls.append({"url": url, "params": captured, "headers": headers or {}})
        assert "field" not in captured
        assert "field" not in {key.lower() for key in captured}
        return await self.handler(url, captured)


def _client(handler) -> tuple[ElsevierClient, RecordingElsevier]:
    recorder = RecordingElsevier(handler)
    return ElsevierClient(request_func=recorder), recorder


def test_affiliation_and_country_normalization():
    parsed = normalize_affiliations(
        [
            {"affilname": "UC Berkeley", "affiliation-country": "United States"},
            {"affilname": "UC Berkeley", "affiliation-country": "United States"},
            {"affilname": "Tsinghua University", "affiliation-country": "China"},
        ]
    )
    assert parsed == [
        {"name": "UC Berkeley", "country": "United States"},
        {"name": "Tsinghua University", "country": "China"},
    ]
    entry = parse_citing_entry(_citing_entry(CITING_A, doi="https://doi.org/10.1000/Cite"))
    assert entry is not None
    assert entry.normalized_doi == "10.1000/cite"
    assert entry.publication_year == 2024
    assert entry.affiliations[0]["country"] == "United States"
    assert len(entry.affiliations) == 2


def test_parse_meta_scopus_id():
    ids = parse_scopus_ids_from_abstract(_meta_payload())
    assert ids.scopus_id == SOURCE_SCOPUS_ID
    assert ids.eid == f"2-s2.0-{SOURCE_SCOPUS_ID}"
    assert ids.citedby_count == 2


@pytest.mark.asyncio
async def test_doi_resolves_via_abstract_meta(elsevier_key):
    async def handler(url, params):
        assert "/content/abstract/doi/" in url
        assert params.get("view") == "META"
        return _response(200, _meta_payload())

    client, recorder = _client(handler)
    ids, source = await resolve_scopus_ids_for_doi("https://doi.org/10.1000/xyz", client=client)
    assert source == "meta"
    assert ids.scopus_id == SOURCE_SCOPUS_ID
    assert len(recorder.calls) == 1
    assert "citation-overview" not in recorder.calls[0]["url"]
    assert "abstract/citation" not in recorder.calls[0]["url"]


@pytest.mark.asyncio
async def test_doi_search_fallback_when_meta_misses(elsevier_key):
    async def handler(url, params):
        if "/content/abstract/doi/" in url:
            return _response(404, {"error": "not found"})
        assert "/content/search/scopus" in url
        assert params["query"] == doi_search_query("10.1000/xyz")
        assert "field" not in params
        return _response(
            200,
            _search_page(
                total=1,
                start=0,
                entries=[
                    {
                        "dc:identifier": f"SCOPUS_ID:{SOURCE_SCOPUS_ID}",
                        "eid": f"2-s2.0-{SOURCE_SCOPUS_ID}",
                    }
                ],
            ),
        )

    client, recorder = _client(handler)
    ids, source = await resolve_scopus_ids_for_doi("10.1000/xyz", client=client)
    assert source == "doi_search"
    assert ids.scopus_id == SOURCE_SCOPUS_ID
    assert len(recorder.calls) == 2


@pytest.mark.asyncio
async def test_ref_pagination_persists_citing_metadata(session_factory, elsevier_key, monkeypatch):
    monkeypatch.setenv("SCOPUS_CITED_BY_PAGE_SIZE", "1")
    monkeypatch.setenv("SCOPUS_CITED_BY_MAX_RESULTS", "50")
    get_settings.cache_clear()
    reset_http_during_transaction_flag()

    async def handler(url, params):
        if "/content/abstract/doi/" in url:
            return _response(200, _meta_payload())
        assert params["query"] == ref_query(SOURCE_SCOPUS_ID)
        assert "field" not in params
        start = int(params["start"])
        if start == 0:
            return _response(
                200,
                _search_page(
                    total=2,
                    start=0,
                    entries=[_citing_entry(CITING_A, doi="10.1000/a")],
                ),
            )
        if start == 1:
            return _response(
                200,
                _search_page(
                    total=2,
                    start=1,
                    entries=[_citing_entry(CITING_B, doi="10.1000/b")],
                ),
            )
        raise AssertionError(f"unexpected start {start}")

    client, recorder = _client(handler)
    async with session_factory() as session:
        work = await _seed_canonical(session, doi="10.1000/xyz")
        service = ScopusCitedByService(session, client=client)
        row = await service.sync_canonical_work(work.id)
        assert row.status == "success"
        assert row.scopus_id == SOURCE_SCOPUS_ID
        assert row.fetched_result_count == 2
        assert http_ran_during_transaction() is False

        citing = (await session.execute(select(ScopusCitingWork))).scalars().all()
        assert {item.scopus_id for item in citing} == {CITING_A, CITING_B}
        first = next(item for item in citing if item.scopus_id == CITING_A)
        assert first.doi == "10.1000/a"
        assert first.normalized_doi == "10.1000/a"
        assert first.title == "Citing paper"
        assert first.cover_date == "2024-03-01"
        assert first.publication_year == 2024
        assert first.source_title == "Nature Physics"
        assert first.affiliations == [
            {"name": "UC Berkeley", "country": "United States"},
            {"name": "LBNL", "country": "United States"},
        ]
        links = (await session.execute(select(ScopusCitationLink))).scalars().all()
        assert len(links) == 2
        assert {link.cited_canonical_work_id for link in links} == {work.id}
        assert {link.cited_scopus_id for link in links} == {SOURCE_SCOPUS_ID}

    ref_calls = [call for call in recorder.calls if call["params"].get("query", "").startswith("REF(")]
    assert len(ref_calls) == 2
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_dedupe_across_cited_source_works(session_factory, elsevier_key):
    async def handler(url, params):
        if "/content/abstract/doi/" in url:
            scopus_id = SOURCE_SCOPUS_ID if "aaa" in url else "85122222222"
            return _response(200, _meta_payload(scopus_id=scopus_id))
        return _response(
            200,
            _search_page(
                total=1,
                start=0,
                entries=[_citing_entry(CITING_A, doi="https://doi.org/10.1000/Shared")],
            ),
        )

    client, _recorder = _client(handler)
    async with session_factory() as session:
        work_a = await _seed_canonical(session, doi="10.1000/aaa", title="A")
        work_b = await _seed_canonical(session, doi="10.1000/bbb", title="B")
        service = ScopusCitedByService(session, client=client)
        await service.sync_canonical_work(work_a.id)
        await service.sync_canonical_work(work_b.id)
        citing_count = await session.scalar(select(func.count()).select_from(ScopusCitingWork))
        link_count = await session.scalar(select(func.count()).select_from(ScopusCitationLink))
        assert citing_count == 1
        assert link_count == 2
        citing = (await session.execute(select(ScopusCitingWork))).scalar_one()
        assert citing.normalized_doi == normalize_doi("https://doi.org/10.1000/Shared")


@pytest.mark.asyncio
async def test_cache_hit_avoids_http(session_factory, elsevier_key):
    handler = AsyncMock(
        side_effect=[
            _response(200, _meta_payload()),
            _response(
                200,
                _search_page(total=0, start=0, entries=[]),
            ),
        ]
    )
    client, recorder = _client(handler)
    async with session_factory() as session:
        work = await _seed_canonical(session, doi="10.1000/xyz")
        service = ScopusCitedByService(session, client=client)
        first = await service.sync_canonical_work(work.id)
        assert first.status == "success"
        first_calls = len(recorder.calls)
        second = await service.sync_canonical_work(work.id)
        assert second.status == "success"
        assert len(recorder.calls) == first_calls


@pytest.mark.asyncio
async def test_partial_provider_failure_does_not_fail_batch(session_factory, elsevier_key):
    async def handler(url, params):
        if "fail-me" in url:
            raise RuntimeError("provider down")
        if "/content/abstract/doi/" in url:
            return _response(200, _meta_payload())
        return _response(200, _search_page(total=0, start=0, entries=[]))

    client, _recorder = _client(handler)
    async with session_factory() as session:
        ok = await _seed_canonical(session, doi="10.1000/ok", title="OK")
        bad = await _seed_canonical(session, doi="10.1000/fail-me", title="Bad")
        service = ScopusCitedByService(session, client=client)
        rows = await service.sync_canonical_works([ok.id, bad.id])
        by_id = {row.canonical_work_id: row for row in rows}
        assert by_id[ok.id].status == "success"
        assert by_id[bad.id].status == "error"
        assert by_id[bad.id].error_message


@pytest.mark.asyncio
async def test_429_retry_on_scopus_search(elsevier_key, monkeypatch):
    monkeypatch.setenv("EXTERNAL_API_DEFAULT_MAX_RETRIES", "1")
    monkeypatch.setenv("EXTERNAL_API_BACKOFF_BASE_SECONDS", "0")
    monkeypatch.setenv("ELSEVIER_RATE_LIMIT_MIN_INTERVAL_SECONDS", "0")
    get_settings.cache_clear()
    await rate_limited_http.reset_provider_limiters_for_tests()
    calls = []

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url, params=None):
            calls.append((url, dict(params or {})))
            request = httpx.Request("GET", url)
            if len(calls) == 1:
                return httpx.Response(
                    429,
                    headers={"Retry-After": "0"},
                    request=request,
                )
            assert "field" not in (params or {})
            return httpx.Response(
                200,
                json=_search_page(total=0, start=0, entries=[]),
                request=request,
            )

    monkeypatch.setattr(rate_limited_http.httpx, "AsyncClient", FakeClient)
    client = ElsevierClient()
    response = await client.search_scopus(ref_query(SOURCE_SCOPUS_ID), start=0, count=25)
    assert response.status_code == 200
    assert len(calls) == 2
    assert calls[0][1]["query"] == f"REF({SOURCE_SCOPUS_ID})"
    assert "field" not in calls[0][1]
    get_settings.cache_clear()
