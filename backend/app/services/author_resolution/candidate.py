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


def candidate_from_provider_result(item: dict[str, Any]) -> AuthorCandidate | None:
    """Map OpenAlex author / arXiv author_name search rows into AuthorCandidate."""
    if not isinstance(item, dict):
        return None

    result_type = item.get("result_type")
    source = (item.get("source") or "").strip().lower()

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
        institutions: list[InstitutionRef] = []
        primary = item.get("primary_institution")
        if isinstance(primary, dict) and (primary.get("id") or primary.get("name")):
            institutions.append(
                InstitutionRef(
                    id=primary.get("id"),
                    name=primary.get("name"),
                    country_code=primary.get("country_code"),
                )
            )
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
            institutions=institutions,
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
