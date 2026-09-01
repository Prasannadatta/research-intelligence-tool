"""Provider-independent author candidate model."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.services.author_resolution.normalization import (
    normalize_author_name,
    split_surname_and_initial,
)


class InstitutionRef(BaseModel):
    id: str | None = None
    name: str | None = None
    country_code: str | None = None


class WorkRef(BaseModel):
    id: str
    id_type: str | None = None
    title: str | None = None
    publication_year: int | None = None


class AuthorCandidate(BaseModel):
    provider: str
    provider_author_id: str
    display_name: str
    normalized_name: str = ""
    surname: str | None = None
    first_initial: str | None = None
    aliases: list[str] = Field(default_factory=list)
    institutions: list[InstitutionRef] = Field(default_factory=list)
    works: list[WorkRef] = Field(default_factory=list)
    coauthors: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    orcid: str | None = None
    works_count: int | None = None
    raw_metadata: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        if not self.normalized_name:
            self.normalized_name = normalize_author_name(self.display_name)
        if self.surname is None or self.first_initial is None:
            surname, initial = split_surname_and_initial(self.normalized_name)
            if self.surname is None:
                self.surname = surname
            if self.first_initial is None:
                self.first_initial = initial


def _institution_refs_from_item(item: dict[str, Any]) -> list[InstitutionRef]:
    institutions: list[InstitutionRef] = []
    seen: set[str] = set()

    def add(ref: InstitutionRef) -> None:
        key = f"{ref.id or ''}|{(ref.name or '').lower()}"
        if key in seen or (not ref.id and not ref.name):
            return
        seen.add(key)
        institutions.append(ref)

    primary = item.get("primary_institution")
    if isinstance(primary, dict):
        add(
            InstitutionRef(
                id=primary.get("id"),
                name=primary.get("name"),
                country_code=primary.get("country_code"),
            )
        )
    for entry in item.get("institutions") or []:
        if not isinstance(entry, dict):
            continue
        add(
            InstitutionRef(
                id=entry.get("id"),
                name=entry.get("name") or entry.get("display_name"),
                country_code=entry.get("country_code"),
            )
        )
    for emp in item.get("employments") or []:
        if not isinstance(emp, dict):
            continue
        add(
            InstitutionRef(
                id=emp.get("id"),
                name=emp.get("name"),
                country_code=emp.get("country_code"),
            )
        )
    return institutions


def _works_from_item(item: dict[str, Any]) -> list[WorkRef]:
    from app.services.author_resolution.scoring import normalize_work_id

    works: list[WorkRef] = []
    seen: set[str] = set()
    rows = list(item.get("works") or []) + list(item.get("sample_papers") or [])
    for paper in rows:
        if not isinstance(paper, dict):
            continue
        raw_id = paper.get("id") or paper.get("result_id")
        if not raw_id:
            continue
        id_type = paper.get("id_type")
        if str(raw_id).startswith("doi:"):
            id_type = id_type or "doi"
        normalized = normalize_work_id(raw_id, id_type=id_type) or str(raw_id).strip()
        if normalized in seen:
            continue
        seen.add(normalized)
        works.append(
            WorkRef(
                id=normalized,
                id_type=id_type or ("doi" if normalized.startswith("doi:") else None),
                title=paper.get("title"),
                publication_year=paper.get("publication_year"),
            )
        )
    return works


def candidate_from_provider_result(item: dict[str, Any]) -> AuthorCandidate | None:
    """Map OpenAlex, arXiv, and ORCID search rows into AuthorCandidate."""
    if not isinstance(item, dict):
        return None

    result_type = item.get("result_type")
    source = (item.get("source") or "").strip().lower()

    if source == "orcid" or str(item.get("result_id") or "").startswith("orcid:"):
        orcid = str(item.get("orcid") or "").strip()
        if not orcid and str(item.get("result_id") or "").startswith("orcid:"):
            orcid = str(item["result_id"]).split(":", 1)[1].strip()
        display_name = str(item.get("display_name") or "").strip()
        if not orcid or not display_name:
            return None
        aliases = [
            str(name).strip()
            for name in (item.get("alternative_names") or [])
            if str(name).strip()
        ]
        return AuthorCandidate(
            provider="orcid",
            provider_author_id=orcid,
            display_name=display_name,
            aliases=aliases,
            institutions=_institution_refs_from_item(item),
            works=_works_from_item(item),
            topics=[
                str(topic.get("name")).strip()
                for topic in (item.get("topics") or [])
                if isinstance(topic, dict) and topic.get("name")
            ],
            orcid=orcid,
            works_count=item.get("works_count"),
            raw_metadata=item,
        )

    if result_type == "author" or (source == "openalex" and item.get("openalex_id")):
        provider_author_id = str(item.get("openalex_id") or "").strip()
        display_name = str(item.get("display_name") or "").strip()
        if not provider_author_id or not display_name:
            return None

        aliases = [
            str(name).strip()
            for name in (item.get("alternative_names") or [])
            if str(name).strip()
        ]
        topics = [
            str(topic.get("name")).strip()
            for topic in (item.get("topics") or [])
            if isinstance(topic, dict) and topic.get("name")
        ]
        return AuthorCandidate(
            provider="openalex",
            provider_author_id=provider_author_id,
            display_name=display_name,
            aliases=aliases,
            institutions=_institution_refs_from_item(item),
            works=_works_from_item(item),
            topics=topics,
            orcid=item.get("orcid"),
            works_count=item.get("works_count"),
            raw_metadata=item,
        )

    if result_type == "author_name" or source == "arxiv":
        display_name = str(item.get("display_name") or "").strip()
        if not display_name:
            return None
        # Stable provider id from result_id when present.
        result_id = str(item.get("result_id") or "")
        if result_id.startswith("arxiv-author-name:"):
            provider_author_id = result_id.split(":", 1)[1]
        else:
            provider_author_id = normalize_author_name(display_name)
        if not provider_author_id:
            return None

        works: list[WorkRef] = []
        for paper in item.get("sample_papers") or []:
            if not isinstance(paper, dict) or not paper.get("result_id"):
                continue
            works.append(
                WorkRef(
                    id=str(paper["result_id"]),
                    id_type="arxiv",
                    title=paper.get("title"),
                    publication_year=paper.get("publication_year"),
                )
            )
        return AuthorCandidate(
            provider="arxiv",
            provider_author_id=provider_author_id,
            display_name=display_name,
            works=works,
            works_count=item.get("matching_papers_count"),
            raw_metadata=item,
        )

    return None


def linked_openalex_id_from_orcid_metadata(
    *,
    orcid: str | None,
    raw_metadata: dict[str, Any] | None,
) -> str | None:
    """
    Return an OpenAlex author id when raw search metadata documents an exact-ORCID link.

    Only trusts linkage already established on an ORCID-anchored search row
    (matching ORCID iD plus openalex_id and/or paired source_records). Never
    infers OpenAlex identity from display name alone.
    """
    from app.integrations.openalex.client import is_valid_openalex_author_id
    from app.integrations.orcid.normalize import normalize_orcid_id

    normalized_orcid = normalize_orcid_id(orcid)
    if not normalized_orcid or not isinstance(raw_metadata, dict):
        return None

    meta_orcid = normalize_orcid_id(raw_metadata.get("orcid"))
    if meta_orcid and meta_orcid != normalized_orcid:
        return None

    source = (raw_metadata.get("source") or "").strip().lower()
    if source and source != "orcid":
        return None

    result_id = str(raw_metadata.get("result_id") or "")
    if result_id and not result_id.startswith("orcid:"):
        return None

    source_records = raw_metadata.get("source_records") or []
    orcid_record_present = False
    openalex_from_records: str | None = None
    if isinstance(source_records, list):
        for row in source_records:
            if not isinstance(row, dict):
                continue
            provider = (row.get("provider") or "").strip().lower()
            provider_author_id = str(row.get("provider_author_id") or "").strip()
            if provider == "orcid":
                if normalize_orcid_id(provider_author_id) == normalized_orcid:
                    orcid_record_present = True
            elif provider == "openalex" and provider_author_id:
                openalex_from_records = provider_author_id

    raw_openalex = str(raw_metadata.get("openalex_id") or "").strip()
    openalex_id = openalex_from_records or raw_openalex or None
    if raw_openalex and openalex_from_records and raw_openalex != openalex_from_records:
        return None
    if not openalex_id or not is_valid_openalex_author_id(openalex_id):
        return None

    if orcid_record_present:
        return openalex_id
    if meta_orcid == normalized_orcid and raw_openalex:
        return openalex_id
    return None
