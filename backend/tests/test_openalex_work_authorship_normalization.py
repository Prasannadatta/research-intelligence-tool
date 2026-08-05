"""Tests for OpenAlex work authorship normalization."""

from __future__ import annotations

from app.integrations.openalex.unified_search import (
    extract_normalized_work_authors,
    normalize_search_work,
)


def test_normalize_search_work_extracts_authorship_affiliations_and_orcid():
    work = {
        "id": "https://openalex.org/W123",
        "title": "Example Work",
        "publication_year": 2024,
        "publication_date": "2024-05-01",
        "type": "article",
        "cited_by_count": 3,
        "language": "en",
        "authorships": [
            {
                "author_position": "first",
                "author": {
                    "id": "https://openalex.org/A111",
                    "display_name": "Author A",
                    "orcid": "https://orcid.org/0000-0001-1111-1111",
                },
                "institutions": [
                    {
                        "id": "https://openalex.org/I1",
                        "display_name": "University X",
                        "country_code": "US",
                    }
                ],
                "countries": ["US"],
            },
            {
                "author_position": "middle",
                "author": {
                    "id": "https://openalex.org/A222",
                    "display_name": "Author B",
                },
                "institutions": [
                    {
                        "id": "https://openalex.org/I2",
                        "display_name": "University Y",
                        "country_code": "CA",
                    },
                    {
                        "id": "https://openalex.org/I3",
                        "display_name": "Institute Z",
                        "country_code": "CA",
                    },
                ],
            },
            {
                "author_position": "last",
                "author": {
                    "id": "https://openalex.org/A333",
                    "display_name": "Author C",
                    "orcid": "0000-0003-3333-3333",
                },
                "institutions": [],
                "raw_affiliation_strings": [],
            },
        ],
        "primary_location": {
            "source": {"display_name": "Nature"},
            "pdf_url": "https://example.com/paper.pdf",
            "landing_page_url": "https://example.com/paper",
        },
        "open_access": {"is_oa": True, "oa_url": "https://example.com/oa"},
        "topics": [{"display_name": "Quantum Information"}],
        "awards": [
            {
                "funder_award_id": "R01GM123456",
                "funder_display_name": "NIH",
            }
        ],
    }

    normalized = normalize_search_work(work)
    assert normalized is not None
    authors = normalized["authors"]
    assert len(authors) == 3
    assert authors[0]["name"] == "Author A"
    assert authors[0]["orcid"] == "0000-0001-1111-1111"
    assert authors[0]["institutions"][0]["name"] == "University X"
    assert authors[1]["institutions"][0]["name"] == "University Y"
    assert authors[1]["institutions"][1]["name"] == "Institute Z"
    assert authors[2]["institutions"] == []
    assert normalized["pdf_url"] == "https://example.com/paper.pdf"
    assert normalized["open_access_url"] == "https://example.com/oa"
    assert normalized["topics"] == ["Quantum Information"]
    assert normalized["citation_count"] == 3


def test_extract_normalized_work_authors_keeps_all_coauthors():
    work = {
        "authorships": [
            {
                "author": {"id": f"https://openalex.org/A{i}", "display_name": f"Author {i}"},
                "institutions": [],
            }
            for i in range(1, 8)
        ]
    }
    authors = extract_normalized_work_authors(work)
    assert len(authors) == 7
    assert authors[0]["author_position"] == 0
    assert authors[-1]["name"] == "Author 7"
