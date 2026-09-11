"""Work candidate extracted from a provider search result."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.work_persistence.normalization import (
    arxiv_id_from_doi,
    extract_provider_work_id,
    extract_publication_timing,
    first_author_name,
    normalize_arxiv_id,
    normalize_doi,
    normalize_grant_number,
    normalize_person_name,
    normalize_pmid,
    normalize_title,
)


@dataclass
class WorkCandidate:
    provider: str
    provider_work_id: str
    title: str
    normalized_title: str
    publication_year: int | None = None
    publication_month: int | None = None
    first_author: str | None = None
    normalized_first_author: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    pmid: str | None = None
    raw_metadata: dict[str, Any] = field(default_factory=dict)
    grant_number: str | None = None
    normalized_grant_number: str | None = None
    grant_verified: bool | None = None
    grant_match_type: str | None = None
    grant_matched_text: str | None = None


def candidate_from_provider_result(
    result: dict[str, Any],
    *,
    provider: str,
) -> WorkCandidate | None:
    provider_work_id = extract_provider_work_id(result, provider)
    title = str(result.get("title") or "").strip()
    if not provider_work_id or not title:
        return None

    first_author = first_author_name(result.get("authors"))
    doi = normalize_doi(result.get("doi"))
    arxiv_id = normalize_arxiv_id(
        result.get("arxiv_id") or (result.get("source_id") if provider == "arxiv" else None)
    )
    if arxiv_id is None:
        arxiv_id = arxiv_id_from_doi(doi)
    pmid = normalize_pmid(result.get("pmid"))

    publication_year, publication_month = extract_publication_timing(result)

    grant_number = result.get("matched_grant_number")
    grant_match = result.get("grant_match") if isinstance(result.get("grant_match"), dict) else {}
    verified = grant_match.get("verified")
    match_type = grant_match.get("type")

    return WorkCandidate(
        provider=provider,
        provider_work_id=str(provider_work_id),
        title=title,
        normalized_title=normalize_title(title),
        publication_year=publication_year,
        publication_month=publication_month,
        first_author=first_author,
        normalized_first_author=normalize_person_name(first_author) or None,
        doi=doi,
        arxiv_id=arxiv_id,
        pmid=pmid,
        raw_metadata=dict(result),
        grant_number=str(grant_number).strip() if grant_number else None,
        normalized_grant_number=(
            normalize_grant_number(str(grant_number)) if grant_number else None
        ),
        grant_verified=bool(verified) if verified is not None else None,
        grant_match_type=str(match_type) if match_type else None,
        grant_matched_text=None,
    )
