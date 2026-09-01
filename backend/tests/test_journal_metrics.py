"""Tests for Scopus journal-metrics enrichment."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.core.issn import compact_issn, extract_issns_from_work_metadata, format_issn
from app.db.base import Base
from app.db.models import JournalMetrics
from app.integrations.elsevier import client as elsevier_client
from app.integrations.elsevier.client import ElsevierClient, elsevier_configured, elsevier_headers
from app.integrations.elsevier.serial_title import SerialTitleMetrics, parse_serial_title_payload
from app.integrations import rate_limited_http
from app.services.analysis.author_insights import AuthorInsightsService
from app.services.journal_metrics.service import (
    JournalMetricsService,
    http_ran_during_transaction,
    metrics_payload,
    reset_http_during_transaction_flag,
)
from tests.test_author_insights import _seed_author, _seed_work

PHYSICAL_REVIEW_A_PAYLOAD = {
    "serial-metadata-response": {
        "entry": [
            {
                "dc:title": "Physical Review A",
                "prism:issn": "10502947",
                "prism:eIssn": "24699926",
                "source-id": "29150",
                "link": [
                    {
                        "@ref": "scopus-source",
                        "@href": "https://www.scopus.com/sourceid/29150",
                    }
                ],
                "citeScoreYearInfoList": {
                    "citeScoreCurrentMetric": "5.1",
                    "citeScoreCurrentMetricYear": "2024",
                },
                "SJRList": {"SJR": [{"@year": "2024", "$": "1.20"}]},
                "SNIPList": {"SNIP": [{"@year": "2024", "$": "1.10"}]},
            }
        ]
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


def test_api_key_loaded_from_settings(elsevier_key):
    settings = get_settings()
    assert settings.elsevier_api_key == "test-elsevier-key"
    assert elsevier_configured() is True
    assert settings.elsevier_configured is True


def test_inst_token_optional(elsevier_key):
    headers = elsevier_headers()
    assert headers["X-ELS-APIKey"] == "test-elsevier-key"
    assert "X-ELS-Insttoken" not in headers
    assert headers["Accept"] == "application/json"


def test_inst_token_header_sent_only_when_configured(elsevier_key, monkeypatch):
    monkeypatch.setenv("ELSEVIER_INST_TOKEN", "campus-token")
    get_settings.cache_clear()
    headers = elsevier_headers()
    assert headers["X-ELS-APIKey"] == "test-elsevier-key"
    assert headers["X-ELS-Insttoken"] == "campus-token"
    get_settings.cache_clear()


@pytest.mark.parametrize(
    ("raw", "compact", "display"),
    [
        ("1050-2947", "10502947", "1050-2947"),
        ("10502947", "10502947", "1050-2947"),
        ("issn 1050-2947", "10502947", "1050-2947"),
        ("1234-567X", "1234567X", "1234-567X"),
        ("not-an-issn", None, None),
    ],
)
def test_issn_normalization(raw, compact, display):
    assert compact_issn(raw) == compact
    assert format_issn(raw) == display


def test_issn_extraction_from_openalex_source_metadata():
    raw = {
        "primary_location": {
            "source": {
                "display_name": "Physical Review A",
                "issn_l": "1050-2947",
                "issn": ["1050-2947", "2469-9926"],
            }
        }
    }
    assert extract_issns_from_work_metadata(raw) == ["10502947", "24699926"]


def test_serial_title_parsing_citescore_sjr_snip_and_year():
    parsed = parse_serial_title_payload(
        PHYSICAL_REVIEW_A_PAYLOAD, http_status=200, view_used="CITESCORE"
    )
    assert parsed.status == "success"
    assert parsed.journal_name == "Physical Review A"
    assert parsed.print_issn == "1050-2947"
    assert parsed.electronic_issn == "2469-9926"
    assert parsed.citescore == 5.1
    assert parsed.citescore_year == 2024
    assert parsed.sjr == 1.2
    assert parsed.sjr_year == 2024
    assert parsed.snip == 1.1
    assert parsed.snip_year == 2024
    assert parsed.scopus_url == "https://www.scopus.com/sourceid/29150"
    assert "10502947" in parsed.all_issns


def test_serial_title_malformed_payload():
    parsed = parse_serial_title_payload({"unexpected": True}, http_status=200)
    assert parsed.status == "error"
    assert parsed.citescore is None


def _fresh_row(**overrides) -> JournalMetrics:
    now = datetime.now(timezone.utc)
    payload = {
        "id": uuid.uuid4(),
        "normalized_issn": "10502947",
        "print_issn": "1050-2947",
        "journal_name": "Physical Review A",
        "citescore": 5.1,
        "citescore_year": 2024,
        "sjr": 1.2,
        "sjr_year": 2024,
        "snip": 1.1,
        "snip_year": 2024,
        "source": "scopus",
        "status": "success",
        "retrieved_at": now,
        "updated_at": now,
        "expires_at": now + timedelta(days=30),
    }
    payload.update(overrides)
    return JournalMetrics(**payload)


@pytest.mark.asyncio
async def test_existing_journal_metrics_reused_without_http(session_factory, elsevier_key):
    fetch = AsyncMock()
    async with session_factory() as session:
        session.add(_fresh_row())
        await session.commit()
        service = JournalMetricsService(session, fetch_fn=fetch)
        row = await service.get_or_enrich_metrics(issn="1050-2947")
        assert row is not None
        assert row.citescore == 5.1
        fetch.assert_not_called()


@pytest.mark.asyncio
async def test_not_found_negative_cache(session_factory, elsevier_key):
    fetch = AsyncMock(return_value=SerialTitleMetrics(status="not_found", http_status=404))
    async with session_factory() as session:
        service = JournalMetricsService(session, fetch_fn=fetch)
        first = await service.get_or_enrich_metrics(issn="9999-9999")
        second = await service.get_or_enrich_metrics(issn="9999-9999")
        assert first is not None
        assert first.status == "not_found"
        assert metrics_payload(first) is None
        assert second.status == "not_found"
        assert fetch.await_count == 1


@pytest.mark.asyncio
async def test_stale_metrics_refresh(session_factory, elsevier_key):
    fetch = AsyncMock(
        return_value=SerialTitleMetrics(
            status="success",
            journal_name="Physical Review A",
            print_issn="1050-2947",
            citescore=6.0,
            citescore_year=2025,
            all_issns=["10502947"],
        )
    )
    async with session_factory() as session:
        session.add(
            _fresh_row(
                citescore=4.0,
                retrieved_at=datetime.now(timezone.utc) - timedelta(days=90),
                updated_at=datetime.now(timezone.utc) - timedelta(days=90),
                expires_at=datetime.now(timezone.utc) - timedelta(days=1),
            )
        )
        await session.commit()
        service = JournalMetricsService(session, fetch_fn=fetch)
        row = await service.get_or_enrich_metrics(issn="1050-2947")
        assert fetch.await_count == 1
        assert row is not None
        assert row.citescore == 6.0


@pytest.mark.asyncio
async def test_batch_lookup_avoids_n_plus_one(session_factory, elsevier_key):
    fetch = AsyncMock(
        return_value=SerialTitleMetrics(
            status="success",
            journal_name="Physical Review A",
            print_issn="1050-2947",
            electronic_issn="2469-9926",
            citescore=5.1,
            all_issns=["10502947", "24699926"],
        )
    )
    async with session_factory() as session:
        service = JournalMetricsService(session, fetch_fn=fetch)
        mapping = await service.enrich_issns(
            ["1050-2947", "10502947", "2469-9926", "1050-2947"]
        )
        assert fetch.await_count == 1
        assert compact_issn("1050-2947") in mapping
        assert mapping[compact_issn("1050-2947")].citescore == 5.1


@pytest.mark.asyncio
async def test_print_and_eissn_share_one_record(session_factory, elsevier_key):
    fetch = AsyncMock(
        return_value=SerialTitleMetrics(
            status="success",
            journal_name="Physical Review A",
            print_issn="1050-2947",
            electronic_issn="2469-9926",
            scopus_source_id="29150",
            citescore=5.1,
            all_issns=["10502947", "24699926"],
        )
    )
    async with session_factory() as session:
        service = JournalMetricsService(session, fetch_fn=fetch)
        await service.enrich_issns(["1050-2947"])
        fetch.reset_mock()
        mapping = await service.enrich_issns(["2469-9926"])
        fetch.assert_not_called()
        assert mapping[compact_issn("2469-9926")].scopus_source_id == "29150"


@pytest.mark.asyncio
async def test_http_not_held_inside_sqlite_transaction(session_factory, elsevier_key):
    reset_http_during_transaction_flag()

    async def fetch(issn: str) -> SerialTitleMetrics:
        return SerialTitleMetrics(
            status="success",
            print_issn="1050-2947",
            citescore=5.1,
            all_issns=[compact_issn(issn) or issn],
        )

    async with session_factory() as session:
        service = JournalMetricsService(session, fetch_fn=fetch)
        await service.enrich_issns(["1050-2947"])
        assert http_ran_during_transaction() is False


@pytest.mark.asyncio
async def test_403_entitlement_handled_cleanly(session_factory, elsevier_key):
    fetch = AsyncMock(
        return_value=SerialTitleMetrics(
            status="unavailable",
            http_status=403,
            entitlement_error="Elsevier entitlement/authorization failed (403).",
        )
    )
    async with session_factory() as session:
        service = JournalMetricsService(session, fetch_fn=fetch)
        row = await service.get_or_enrich_metrics(issn="1050-2947")
        assert row is not None
        assert row.status == "unavailable"
        assert metrics_payload(row) is None


@pytest.mark.asyncio
async def test_429_bounded_retry(elsevier_key, monkeypatch):
    monkeypatch.setenv("EXTERNAL_API_DEFAULT_MAX_RETRIES", "1")
    monkeypatch.setenv("EXTERNAL_API_BACKOFF_BASE_SECONDS", "0")
    monkeypatch.setenv("ELSEVIER_RATE_LIMIT_MIN_INTERVAL_SECONDS", "0")
    get_settings.cache_clear()
    await rate_limited_http.reset_provider_limiters_for_tests()
    calls = []

    captured_headers = []

    class FakeClient:
        def __init__(self, **kwargs):
            captured_headers.append(kwargs.get("headers") or {})

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url, params=None):
            calls.append((url, params))
            request = httpx.Request("GET", url)
            if len(calls) == 1:
                return httpx.Response(
                    429,
                    headers={"Retry-After": "0"},
                    request=request,
                )
            return httpx.Response(200, json=PHYSICAL_REVIEW_A_PAYLOAD, request=request)

    monkeypatch.setattr(rate_limited_http.httpx, "AsyncClient", FakeClient)
    client = ElsevierClient()
    response = await client.get_serial_title("1050-2947", view="CITESCORE")
    assert response.status_code == 200
    assert len(calls) == 2
    assert "test-elsevier-key" not in str(calls)
    assert captured_headers
    assert captured_headers[0].get("X-ELS-APIKey") == "test-elsevier-key"
    assert "X-ELS-Insttoken" not in captured_headers[0]
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_insights_includes_journal_metrics_and_survives_elsevier_outage(
    session_factory, elsevier_key, monkeypatch
):
    fetch = AsyncMock(
        return_value=SerialTitleMetrics(
            status="success",
            journal_name="Physical Review A",
            print_issn="1050-2947",
            citescore=5.1,
            citescore_year=2024,
            sjr=1.2,
            sjr_year=2024,
            snip=1.1,
            snip_year=2024,
            scopus_url="https://www.scopus.com/sourceid/29150",
            all_issns=["10502947"],
        )
    )
    async with session_factory() as session:
        author_a = await _seed_author(session, name="Author A", openalex_id="A1")
        author_b = await _seed_author(session, name="Author B", openalex_id="A2")
        await _seed_work(
            session,
            title="Shared Paper One",
            year=2023,
            provider_work_id="W1",
            selected_authors=[author_a, author_b],
            citation_count=10,
            venue="Physical Review A",
            issn="1050-2947",
        )
        await _seed_work(
            session,
            title="Shared Paper Two",
            year=2022,
            provider_work_id="W2",
            selected_authors=[author_a, author_b],
            citation_count=8,
            venue="Physical Review A",
            issn="1050-2947",
        )
        await session.commit()

        monkeypatch.setattr(
            "app.services.journal_metrics.service.fetch_serial_title_metrics",
            fetch,
        )
        service = AuthorInsightsService(session)
        result = await service.build_dashboard(
            authors=[
                {"canonical_author_id": str(author_a.id), "display_name": "Author A"},
                {"canonical_author_id": str(author_b.id), "display_name": "Author B"},
            ]
        )
        row = result["top_journals"][0]
        assert row["venue"] == "Physical Review A"
        assert row["publication_count"] == 2
        assert row["issn"] == "1050-2947"
        assert row["journal_metrics"]["citescore"] == 5.1
        assert row["journal_metrics"]["sjr"] == 1.2
        assert row["journal_metrics"]["snip"] == 1.1
        assert row["journal_metrics"]["source"] == "scopus"
        assert fetch.await_count == 1

        fetch.side_effect = RuntimeError("elsevier down")
        result = await service.build_dashboard(
            authors=[
                {"canonical_author_id": str(author_a.id), "display_name": "Author A"},
                {"canonical_author_id": str(author_b.id), "display_name": "Author B"},
            ]
        )
        assert result["top_journals"][0]["journal_metrics"]["citescore"] == 5.1
        assert result["metrics"]["total_unique_publications"] == 2


@pytest.mark.asyncio
async def test_insights_survives_elsevier_unavailable_without_cache(
    session_factory, elsevier_key, monkeypatch
):
    async def boom(_issn: str, client=None):
        raise RuntimeError("elsevier down")

    monkeypatch.setattr(
        "app.services.journal_metrics.service.fetch_serial_title_metrics",
        boom,
    )
    async with session_factory() as session:
        author_a = await _seed_author(session, name="Author A", openalex_id="A1")
        author_b = await _seed_author(session, name="Author B", openalex_id="A2")
        await _seed_work(
            session,
            title="Shared Paper One",
            year=2023,
            provider_work_id="W1",
            selected_authors=[author_a, author_b],
            citation_count=10,
            venue="Physical Review A",
            issn="1050-2947",
        )
        await session.commit()
        service = AuthorInsightsService(session)
        result = await service.build_dashboard(
            authors=[
                {"canonical_author_id": str(author_a.id), "display_name": "Author A"},
                {"canonical_author_id": str(author_b.id), "display_name": "Author B"},
            ]
        )
        assert result["top_journals"][0]["venue"] == "Physical Review A"
        assert result["top_journals"][0]["journal_metrics"] is None
        assert result["metrics"]["total_unique_publications"] == 1
