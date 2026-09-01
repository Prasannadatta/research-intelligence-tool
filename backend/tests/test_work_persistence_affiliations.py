"""Tests for publication-specific authorship affiliation persistence payloads."""

from __future__ import annotations

from app.services.work_persistence.repository import _authorships_from_raw_metadata


def test_structured_affiliation_payload_is_persistence_ready():
    rows = _authorships_from_raw_metadata(
        {
            "authors": [
                {
                    "id": "A1111111111",
                    "name": "Jane Doe",
                    "institutions": [
                        {
                            "id": "I123",
                            "name": "UC Berkeley",
                            "country_code": "US",
                        }
                    ],
                    "raw_affiliation_strings": [
                        "Department of Bioengineering, UC Berkeley, United States"
                    ],
                }
            ]
        },
        provider="openalex",
    )

    assert rows[0]["institution_ids"] == ["I123"]
    assert rows[0]["countries"] == ["US"]
    assert rows[0]["institutions"][0]["name"] == "UC Berkeley"
    assert rows[0]["raw_metadata"]["department"] == "Department of Bioengineering"
    assert rows[0]["raw_metadata"]["raw_affiliation_text"] == (
        "Department of Bioengineering, UC Berkeley, United States"
    )
    assert rows[0]["raw_metadata"]["affiliation_source"] == "structured_authorship"


def test_raw_affiliation_does_not_overwrite_structured_institution():
    rows = _authorships_from_raw_metadata(
        {
            "authors": [
                {
                    "id": "A2222222222",
                    "name": "Alex Doe",
                    "institutions": [
                        {
                            "id": "I999",
                            "name": "Structured University",
                            "country_code": "CA",
                        }
                    ],
                    "raw_affiliation_strings": [
                        "Dept. of Physics, Raw Text University, Canada"
                    ],
                }
            ]
        },
        provider="openalex",
    )

    assert rows[0]["institutions"] == [
        {
            "id": "I999",
            "name": "Structured University",
            "country_code": "CA",
            "type": None,
            "department": "Dept. of Physics",
            "source": "structured_authorship",
            "affiliation_source": "structured_authorship",
            "affiliation_confidence": 0.95,
            "raw_affiliation_text": "Dept. of Physics, Raw Text University, Canada",
        }
    ]
    assert rows[0]["raw_metadata"]["department"] == "Dept. of Physics"


def test_missing_explicit_affiliation_terms_are_not_fabricated():
    rows = _authorships_from_raw_metadata(
        {
            "authors": [
                {
                    "id": "A3333333333",
                    "name": "Sam Doe",
                    "institutions": [],
                    "raw_affiliation_strings": ["Some University, USA"],
                }
            ]
        },
        provider="openalex",
    )

    assert rows[0]["institutions"] == []
    assert rows[0]["countries"] == []
    assert rows[0]["raw_metadata"]["raw_affiliation_text"] == "Some University, USA"
    assert "department" not in rows[0]["raw_metadata"]
    assert rows[0]["raw_metadata"]["affiliation_source"] == "raw_affiliation_text"
