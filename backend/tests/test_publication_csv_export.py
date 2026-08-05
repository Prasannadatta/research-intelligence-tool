"""Tests for publication CSV export (authors + grants)."""

from __future__ import annotations

import csv
import io
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.integrations.arxiv.client import reset_arxiv_client_state_for_tests
from app.main import app
from app.services.analysis.publication_csv_export import (
    ESSENTIAL_COLUMNS,
    build_authors_export_filename,
    build_export_table,
    build_grant_export_filename,
    escape_csv_formula,
    iter_csv_bytes,
    join_aligned,
    publication_item_to_row_dict,
    select_export_columns,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_settings(monkeypatch):
    monkeypatch.setenv("WORK_PERSISTENCE_ENABLED", "false")
    monkeypatch.setenv("AUTHOR_RESOLUTION_ENABLED", "false")
    monkeypatch.setenv("PROVIDER_SEARCH_CACHE_ENABLED", "false")
    monkeypatch.setenv("OPENALEX_API_KEY", "test-key")
    monkeypatch.setenv("ARXIV_ENABLED", "false")
    reset_arxiv_client_state_for_tests()
    get_settings.cache_clear()
    yield
    reset_arxiv_client_state_for_tests()
    get_settings.cache_clear()


def _author(name="Eneet Kaur", cid="author-1", oid="A1234567890"):
    return {
        "canonical_author_id": cid,
        "provider": "openalex",
        "provider_author_id": oid,
        "display_name": name,
    }


def _work(
    *,
    work_id: str,
    title: str,
    year: int = 2021,
    journal: str = "Nature Medicine",
    grants: list | None = None,
    authors: list | None = None,
    providers: list | None = None,
    citation_count: int | None = 12,
):
    return {
        "result_id": f"openalex:{work_id}",
        "result_type": "work",
        "openalex_id": work_id,
        "title": title,
        "authors": authors
        or [{"id": "A1234567890", "name": "Eneet Kaur", "orcid": "0000-0001-2345-6789"}],
        "publication_year": year,
        "publication_date": f"{year}-06-15",
        "primary_source": journal,
        "cited_by_count": citation_count,
        "citation_count": citation_count,
        "doi": f"10.1000/{work_id}",
        "pmid": "12345678",
        "arxiv_id": None,
        "work_type": "article",
        "is_open_access": True,
        "url": f"https://doi.org/10.1000/{work_id}",
        "source": "openalex",
        "providers": providers or ["openalex"],
        "grants": grants
        or [
            {
                "award_id": "R01GM123456",
                "grant_number": "R01GM123456",
                "funder_name": "National Institutes of Health",
                "funder": "National Institutes of Health",
                "agency": "NIH",
                "verified": True,
                "match_type": "structured_award_relationship",
                "provider": "openalex",
            }
        ],
        "analysis_match": {"verified": True, "method": "provider_author_ids"},
    }


def _parse_csv_response(response):
    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    assert "attachment" in response.headers["content-disposition"]
    text = response.content.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))
    header = rows[0]
    body = rows[1:]
    return header, body


def test_escape_and_aligned_join():
    assert escape_csv_formula("=1+1") == "'=1+1"
    assert escape_csv_formula(None) == ""
    assert escape_csv_formula("null") == ""
    assert join_aligned(["Jane Doe", "John Smith"]) == "Jane Doe | John Smith"
    assert join_aligned(["0001", "", "0003"]) == "0001 |  | 0003"
    assert join_aligned(["", "", ""]) == ""


def test_filename_reflects_authors_and_year_range():
    day = date(2026, 8, 4)
    assert (
        build_authors_export_filename([_author("Eneet Kaur")], export_date=day)
        == "eneet-kaur-publications-2026-08-04.csv"
    )
    assert (
        build_authors_export_filename(
            [_author("Eneet Kaur"), _author("Mark Wilde", "a2", "A2")],
            export_date=day,
        )
        == "eneet-kaur-and-mark-wilde-common-publications-2026-08-04.csv"
    )
    assert (
        build_authors_export_filename(
            [
                _author("A", "1", "A1"),
                _author("B", "2", "A2"),
                _author("C", "3", "A3"),
                _author("D", "4", "A4"),
            ],
            export_date=day,
        )
        == "common-publications-4-authors-2026-08-04.csv"
    )
    assert (
        build_authors_export_filename(
            [_author("Eneet Kaur")],
            filters={"from_year": 2020, "to_year": 2025},
            export_date=day,
        )
        == "eneet-kaur-publications-2020-to-2025.csv"
    )
    assert (
        build_grant_export_filename("R01GM123456", export_date=day)
        == "grant-R01GM123456-publications-2026-08-04.csv"
    )
    assert (
        build_grant_export_filename(
            "R01GM123456",
            provider="openalex",
            filters={"from_year": 2020, "to_year": 2025},
            export_date=day,
        )
        == "grant-R01GM123456-openalex-2020-to-2025.csv"
    )


def test_internal_ids_and_abstract_absent():
    item = _work(work_id="W1", title="Paper")
    item["abstract"] = "Secret abstract"
    item["summary"] = "Secret summary"
    item["canonical_work_id"] = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    row = publication_item_to_row_dict(item)
    assert "Abstract" not in row
    assert "Canonical Work ID" not in row
    assert "Author Canonical IDs" not in row
    assert "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee" not in row.values()
    assert "Secret abstract" not in row.values()


def test_empty_optional_columns_removed():
    item = {
        "title": "Only Title",
        "authors": [{"name": "Ada"}],
        "providers": ["openalex"],
        "url": "https://example.com",
        "journal": "Nature",
        "publication_date": "2024-01-01",
        "grants": [],
    }
    columns, matrix = build_export_table([item])
    for essential in ESSENTIAL_COLUMNS:
        assert essential in columns
    assert "DOI" not in columns
    assert "Publisher" not in columns
    assert "Searched Grant" not in columns
    assert matrix[0][columns.index("Title")] == "Only Title"
    # Essential grant column remains even when empty.
    assert "Grant Numbers" in columns
    assert matrix[0][columns.index("Grant Numbers")] == ""


def test_author_alignment_preserves_blank_slots():
    authors = [
        {
            "name": "Jane Doe",
            "orcid": "0000-0001-1111-1111",
            "canonical_author_id": "aaaaaaaa-1111-4111-8111-111111111111",
            "institutions": [{"name": "University A"}],
            "countries": ["US"],
        },
        {
            "name": "John Smith",
            "canonical_author_id": "bbbbbbbb-2222-4222-8222-222222222222",
            "institutions": [{"name": "University B"}],
            "countries": ["CA"],
        },
        {
            "name": "Alex Chen",
            "orcid": "0000-0003-3333-3333",
            "canonical_author_id": "cccccccc-3333-4333-8333-333333333333",
            "institutions": [{"name": "University C"}, {"name": "Lab C"}],
            "countries": ["UK"],
        },
    ]
    row = publication_item_to_row_dict(
        {
            "title": "Aligned",
            "authors": authors,
            "providers": ["openalex"],
            "url": "https://example.com",
            "journal": "Nature",
            "publication_date": "2024-01-01",
            "grants": [],
        }
    )
    assert row["Authors"] == "Jane Doe | John Smith | Alex Chen"
    assert row["Author ORCIDs"] == "0000-0001-1111-1111 |  | 0000-0003-3333-3333"
    assert (
        row["Author Affiliations"]
        == "University A | University B | University C, Lab C"
    )
    assert row["Author Countries"] == "US | CA | UK"


def test_publication_affiliations_override_profile_institutions():
    authors = [
        {
            "name": "Jane Doe",
            "canonical_author_id": "aaaaaaaa-1111-4111-8111-111111111111",
            "institutions": [{"name": "Paper University"}],
        }
    ]
    meta = {
        "aaaaaaaa-1111-4111-8111-111111111111": {
            "orcid": "0000-0001-1111-1111",
            "institutions": ["Career University"],
            "countries": ["US"],
            "country": "US",
        }
    }
    row = publication_item_to_row_dict(
        {
            "title": "Priority",
            "authors": authors,
            "providers": ["openalex"],
            "url": "https://example.com",
            "journal": "Nature",
            "publication_date": "2024-01-01",
            "grants": [],
        },
        author_metadata=meta,
    )
    assert row["Author Affiliations"] == "Paper University"
    assert "Career University" not in row["Author Affiliations"]


def test_canonical_profile_affiliation_fallback():
    authors = [
        {
            "name": "Jane Doe",
            "canonical_author_id": "aaaaaaaa-1111-4111-8111-111111111111",
            "institutions": [],
        }
    ]
    meta = {
        "aaaaaaaa-1111-4111-8111-111111111111": {
            "orcid": "0000-0001-1111-1111",
            "institutions": ["Career University"],
            "countries": ["US"],
            "country": "US",
        }
    }
    row = publication_item_to_row_dict(
        {
            "title": "Fallback",
            "authors": authors,
            "providers": ["openalex"],
            "url": "https://example.com",
            "journal": "Nature",
            "publication_date": "2024-01-01",
            "grants": [],
        },
        author_metadata=meta,
    )
    assert row["Author Affiliations"] == "Career University"


def test_coauthor_metadata_not_only_selected_authors():
    item = {
        "title": "Many Authors",
        "authors": [
            {"name": "Selected Author", "id": "A1111111111", "orcid": "0000-0001-0001-0001"},
            {
                "name": "Co Author",
                "id": "A2222222222",
                "institutions": [{"name": "Toronto", "country_code": "CA"}],
                "orcid": "0000-0002-0002-0002",
            },
        ],
        "providers": ["openalex"],
        "url": "https://example.com",
        "journal": "Nature",
        "publication_date": "2024-01-01",
        "grants": [],
    }
    row = publication_item_to_row_dict(item)
    assert row["Authors"] == "Selected Author | Co Author"
    assert "Toronto" in row["Author Affiliations"]
    assert "0000-0002-0002-0002" in row["Author ORCIDs"]


def test_unresolved_authors_keep_provider_authorship_metadata():
    item = {
        "title": "Unresolved",
        "authors": [
            {
                "name": "Unknown Person",
                "id": "A9999999999",
                "orcid": "0000-0009-9999-9999",
                "institutions": [{"name": "From Paper", "country_code": "DE"}],
                "countries": ["DE"],
                "unresolved": True,
            }
        ],
        "providers": ["openalex"],
        "url": "https://example.com",
        "journal": "Nature",
        "publication_date": "2024-01-01",
        "grants": [],
    }
    row = publication_item_to_row_dict(item)
    assert row["Authors"] == "Unknown Person"
    assert row["Author Affiliations"] == "From Paper"
    assert row["Author ORCIDs"] == "0000-0009-9999-9999"
    assert row["Author Countries"] == "DE"


def test_citation_fallback_to_provider_metadata_preserves_zero():
    zero = publication_item_to_row_dict(
        {
            "title": "Zero",
            "authors": [{"name": "Ada"}],
            "providers": ["openalex"],
            "url": "https://example.com",
            "journal": "Nature",
            "publication_date": "2024-01-01",
            "citation_count": 0,
            "grants": [],
        }
    )
    fallback = publication_item_to_row_dict(
        {
            "id": "cccccccc-3333-4333-8333-333333333333",
            "canonical_work_id": "cccccccc-3333-4333-8333-333333333333",
            "title": "From Provider",
            "authors": [{"name": "Ada"}],
            "providers": ["openalex"],
            "url": "https://example.com",
            "journal": "Nature",
            "publication_date": "2024-01-01",
            "grants": [],
        },
        work_metadata={
            "cccccccc-3333-4333-8333-333333333333": {
                "citation_count": 7,
                "cited_by_count": 7,
                "grants": [],
                "topics": [],
                "authorships": [],
            }
        },
    )
    assert zero["Citation Count"] == "0"
    assert fallback["Citation Count"] == "7"

def test_sources_use_human_labels():
    row = publication_item_to_row_dict(
        _work(work_id="W1", title="Labeled", providers=["openalex", "arxiv"])
    )
    assert row["Sources"] == "OpenAlex | arXiv"


def test_csv_quoting_and_utf8():
    item = {
        "title": 'Hello, "World"\nLine 2',
        "authors": [{"display_name": "José García"}],
        "publication_year": 2024,
        "journal": "Nature, Medicine",
        "publication_date": "2024-01-01",
        "grants": [],
        "providers": ["openalex"],
        "url": "https://example.com",
    }
    chunks = list(iter_csv_bytes([item]))
    text = b"".join(chunks).decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))
    header = rows[0]
    assert rows[1][header.index("Title")] == 'Hello, "World"\nLine 2'
    assert rows[1][header.index("Authors")] == "José García"


def test_authors_export_includes_all_filtered_not_only_page():
    results = [
        _work(work_id=f"W{i}", title=f"Paper {i}", year=2020 + (i % 3))
        for i in range(25)
    ]
    with patch(
        "app.services.analysis.author_publications.search_works_by_author_ids",
        new_callable=AsyncMock,
    ) as mock_oa:
        mock_oa.return_value = {
            "results": results,
            "next_cursor": None,
            "has_more": False,
        }
        list_response = client.post(
            "/api/analysis/authors/publications",
            json={"authors": [_author()], "limit": 20},
        )
        assert list_response.status_code == 200
        assert len(list_response.json()["items"]) == 20

        export_response = client.post(
            "/api/analysis/authors/publications/export",
            json={
                "authors": [_author()],
                "filters": {"from_year": 2020, "to_year": 2026},
            },
        )

    header, rows = _parse_csv_response(export_response)
    assert len(rows) == 25
    assert "Abstract" not in header
    assert "Canonical Work ID" not in header
    assert "eneet-kaur-publications-2020-to-2026" in export_response.headers[
        "content-disposition"
    ]


def test_authors_export_respects_applied_filters():
    results = [
        _work(work_id="W1", title="In Range", year=2021, journal="Nature Medicine"),
        _work(work_id="W2", title="Out of Range", year=2010, journal="Nature Medicine"),
        _work(work_id="W3", title="Wrong Venue", year=2021, journal="Science"),
    ]
    with patch(
        "app.services.analysis.author_publications.search_works_by_author_ids",
        new_callable=AsyncMock,
    ) as mock_oa:
        mock_oa.return_value = {
            "results": results,
            "next_cursor": None,
            "has_more": False,
        }
        response = client.post(
            "/api/analysis/authors/publications/export",
            json={
                "authors": [_author()],
                "filters": {
                    "from_year": 2020,
                    "to_year": 2026,
                    "venues": ["Nature Medicine"],
                    "sources": ["openalex"],
                },
            },
        )
    header, rows = _parse_csv_response(response)
    titles = [row[header.index("Title")] for row in rows]
    assert titles == ["In Range"]


def test_authors_export_deduplicates_canonical_works():
    duplicate = _work(work_id="W1", title="Once")
    with patch(
        "app.services.analysis.author_publications.search_works_by_author_ids",
        new_callable=AsyncMock,
    ) as mock_oa:
        mock_oa.return_value = {
            "results": [duplicate, dict(duplicate)],
            "next_cursor": None,
            "has_more": False,
        }
        response = client.post(
            "/api/analysis/authors/publications/export",
            json={"authors": [_author()]},
        )
    _, rows = _parse_csv_response(response)
    assert len(rows) == 1


def test_multi_author_filename_and_intersection():
    with patch(
        "app.services.analysis.author_publications.search_works_by_author_ids",
        new_callable=AsyncMock,
    ) as mock_oa:
        mock_oa.return_value = {
            "results": [_work(work_id="WCommon", title="Shared")],
            "next_cursor": None,
            "has_more": False,
        }
        response = client.post(
            "/api/analysis/authors/publications/export",
            json={
                "authors": [
                    _author("Eneet Kaur", "c1", "A1111111111"),
                    _author("Mark Wilde", "c2", "A2222222222"),
                ]
            },
        )
        assert len(mock_oa.await_args.kwargs["author_id_groups"]) == 2
    assert "eneet-kaur-and-mark-wilde-common-publications" in response.headers[
        "content-disposition"
    ]


def test_grant_export_populates_searched_grant_and_all_grants():
    grant_work = {
        "result_id": "openalex:W9",
        "result_type": "work",
        "openalex_id": "W9",
        "title": "Multi Grant Paper",
        "authors": [{"id": "A1", "name": "Ada"}],
        "publication_year": 2022,
        "publication_date": "2022-03-01",
        "primary_source": "Cell",
        "cited_by_count": 3,
        "url": "https://example.com/w9",
        "source": "openalex",
        "grants": [
            {
                "grant_number": "R01GM123456",
                "award_id": "R01GM123456",
                "funder": "National Institutes of Health",
                "funder_name": "National Institutes of Health",
                "agency": "NIH",
                "verified": True,
                "match_type": "structured_award_relationship",
                "provider": "openalex",
            },
            {
                "grant_number": "P30CA045508",
                "award_id": "P30CA045508",
                "funder": "National Cancer Institute",
                "funder_name": "National Cancer Institute",
                "agency": "NIH",
                "verified": True,
                "match_type": "structured_award_relationship",
                "provider": "openalex",
            },
        ],
    }
    with patch(
        "app.services.grants.publications.search_publications_for_grant_number",
        new_callable=AsyncMock,
    ) as mock_search:
        mock_search.return_value = {
            "results": [grant_work],
            "next_cursor": None,
            "has_more": False,
        }
        response = client.post(
            "/api/grants/R01GM123456/publications/export",
            json={
                "provider": "openalex",
                "filters": {"from_year": 2020, "to_year": 2026},
            },
        )

    header, rows = _parse_csv_response(response)
    assert "Searched Grant" in header
    assert rows[0][header.index("Searched Grant")] == "R01GM123456"
    grants_cell = rows[0][header.index("Grant Numbers")]
    assert "R01GM123456" in grants_cell
    assert "P30CA045508" in grants_cell
    assert "[" not in grants_cell
    assert "grant-R01GM123456-openalex-2020-to-2026" in response.headers[
        "content-disposition"
    ]


def test_no_abstract_enrichment_provider_calls():
    with patch(
        "app.services.analysis.author_publications.search_works_by_author_ids",
        new_callable=AsyncMock,
    ) as mock_oa, patch(
        "app.integrations.openalex.client.fetch_openalex_author_payload",
        new_callable=AsyncMock,
    ) as mock_fetch_author, patch(
        "app.integrations.openalex.client.get_openalex_author",
        new_callable=AsyncMock,
    ) as mock_get_author:
        mock_oa.return_value = {
            "results": [_work(work_id="W1", title="No Abstract Fetch")],
            "next_cursor": None,
            "has_more": False,
        }
        response = client.post(
            "/api/analysis/authors/publications/export",
            json={"authors": [_author()]},
        )
    assert response.status_code == 200
    mock_fetch_author.assert_not_called()
    mock_get_author.assert_not_called()


def test_shared_formatter_used_for_author_and_grant_rows():
    item = _work(work_id="W1", title="Shared Formatter")
    author_row = publication_item_to_row_dict(item)
    grant_row = publication_item_to_row_dict(item, searched_grant="R01GM123456")
    assert author_row["Title"] == grant_row["Title"]
    assert "Searched Grant" not in author_row
    assert grant_row["Searched Grant"] == "R01GM123456"
    columns = select_export_columns([grant_row], include_searched_grant=True)
    assert "Searched Grant" in columns


def test_stored_institutions_included_from_batch_metadata():
    item = _work(
        work_id="W1",
        title="With Institutions",
        authors=[
            {
                "name": "Eneet Kaur",
                "canonical_author_id": "aaaaaaaa-1111-4111-8111-111111111111",
                "id": "A1234567890",
            }
        ],
    )
    meta = {
        "aaaaaaaa-1111-4111-8111-111111111111": {
            "orcid": "0000-0001-5555-5555",
            "institutions": ["UC Berkeley", "Lawrence Berkeley National Laboratory"],
            "countries": ["US"],
            "country": "US",
        }
    }
    row = publication_item_to_row_dict(item, author_metadata=meta)
    assert (
        row["Author Affiliations"]
        == "UC Berkeley, Lawrence Berkeley National Laboratory"
    )
    assert row["Author Countries"] == "US"
    assert row["Author ORCIDs"] == "0000-0001-5555-5555"


@pytest.mark.asyncio
async def test_batch_metadata_loaders_use_grouped_queries():
    """Ensure export metadata helpers issue a small number of grouped queries."""
    from app.services.analysis import publication_csv_export as export_mod

    items = [
        _work(
            work_id="W1",
            title="A",
            authors=[
                {
                    "name": "Ada",
                    "canonical_author_id": "aaaaaaaa-1111-4111-8111-111111111111",
                    "id": "A1111111111",
                }
            ],
        ),
        _work(
            work_id="W2",
            title="B",
            authors=[
                {
                    "name": "Grace",
                    "canonical_author_id": "bbbbbbbb-2222-4222-8222-222222222222",
                    "id": "A2222222222",
                }
            ],
        ),
    ]
    # Force UUID-looking work ids so work loader attempts a query.
    items[0]["canonical_work_id"] = "cccccccc-3333-4333-8333-333333333333"
    items[0]["id"] = items[0]["canonical_work_id"]
    items[1]["canonical_work_id"] = "dddddddd-4444-4444-8444-444444444444"
    items[1]["id"] = items[1]["canonical_work_id"]

    session = AsyncMock()
    result = AsyncMock()
    result.scalars = lambda: result
    result.all = lambda: []
    session.execute = AsyncMock(return_value=result)

    await export_mod._batch_load_author_metadata(session, items)
    await export_mod._batch_load_work_metadata(session, items)

    # Grouped lookups: openalex providers, canonical authors, profiles,
    # institutions, and one canonical-works query — not one execute per item.
    assert session.execute.await_count <= 5
    assert session.execute.await_count >= 1
