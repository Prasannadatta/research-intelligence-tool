"""Parse and normalize arXiv Atom API responses."""

from __future__ import annotations

import re
import unicodedata
from typing import Any
from urllib.parse import urlparse

import feedparser

# Newer: YYMM.NNNNN ; older: archive/YYMMNNN ; optional version suffix.
_ARXIV_ID_RE = re.compile(
    r"(?:arxiv[:/]\s*)?"
    r"(?P<id>"
    r"(?:\d{4}\.\d{4,5})"
    r"|(?:[a-z\-]+(?:\.[A-Z]{2})?/\d{7})"
    r")"
    r"(?:v(?P<version>\d+))?",
    re.IGNORECASE,
)


def normalize_arxiv_query(query: str | None) -> str:
    return " ".join((query or "").split())


def normalize_author_name_for_id(name: str) -> str:
    """Deterministic id key; preserve initials/punctuation differences."""
    text = unicodedata.normalize("NFKC", name or "")
    text = " ".join(text.strip().lower().split())
    return text


def extract_arxiv_id(value: str | None) -> tuple[str | None, str | None]:
    """
    Return (canonical_id_without_version, version_or_None).

    Accepts abs URLs, id URNs, and bare ids.
    """
    if not value:
        return None, None

    text = str(value).strip()
    parsed = urlparse(text)
    path = parsed.path if parsed.scheme else text
    path = path.replace("/abs/", "/").replace("/pdf/", "/")
    path = path.removesuffix(".pdf")
    candidate = path.rsplit("/", 1)[-1] if "/" in path else path
    if ":" in candidate and not candidate.lower().startswith("arxiv:"):
        candidate = candidate.rsplit(":", 1)[-1]

    match = _ARXIV_ID_RE.search(candidate) or _ARXIV_ID_RE.search(text)
    if not match:
        return None, None

    arxiv_id = match.group("id")
    version = match.group("version")
    return arxiv_id, version


def _entry_link(entry: Any, rel: str | None = None, title: str | None = None) -> str | None:
    links = getattr(entry, "links", None) or []
    for link in links:
        href = getattr(link, "href", None) or (link.get("href") if isinstance(link, dict) else None)
        if not href:
            continue
        link_rel = getattr(link, "rel", None) or (link.get("rel") if isinstance(link, dict) else None)
        link_title = getattr(link, "title", None) or (
            link.get("title") if isinstance(link, dict) else None
        )
        if rel and link_rel != rel:
            continue
        if title and (link_title or "").lower() != title.lower():
            continue
        return str(href).strip() or None
    return None


def _entry_categories(entry: Any) -> list[str]:
    tags = getattr(entry, "tags", None) or []
    categories: list[str] = []
    for tag in tags:
        term = getattr(tag, "term", None) or (tag.get("term") if isinstance(tag, dict) else None)
        text = str(term or "").strip()
        if text and text not in categories:
            categories.append(text)
    return categories


def _entry_authors(entry: Any) -> list[dict[str, Any]]:
    authors: list[dict[str, Any]] = []
    for index, author in enumerate(getattr(entry, "authors", None) or []):
        name = getattr(author, "name", None) or (
            author.get("name") if isinstance(author, dict) else None
        )
        text = str(name or "").strip()
        if text:
            authors.append(
                {
                    "id": None,
                    "name": text,
                    "display_name": text,
                    "orcid": None,
                    "author_position": index,
                    "institutions": [],
                    "institution_ids": [],
                    "countries": [],
                    "provider_ids": {"openalex": [], "orcid": [], "arxiv": []},
                }
            )
    if not authors:
        single = getattr(entry, "author", None)
        text = str(single or "").strip()
        if text:
            authors.append(
                {
                    "id": None,
                    "name": text,
                    "display_name": text,
                    "orcid": None,
                    "author_position": 0,
                    "institutions": [],
                    "institution_ids": [],
                    "countries": [],
                    "provider_ids": {"openalex": [], "orcid": [], "arxiv": []},
                }
            )
    return authors


def _year_from_date(date_text: str | None) -> int | None:
    if not date_text:
        return None
    match = re.match(r"^(\d{4})", str(date_text).strip())
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _date_only(date_text: str | None) -> str | None:
    if not date_text:
        return None
    text = str(date_text).strip()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    return text or None


def normalize_arxiv_work(entry: Any) -> dict[str, Any] | None:
    raw_id = getattr(entry, "id", None) or ""
    arxiv_id, version = extract_arxiv_id(raw_id)
    if not arxiv_id:
        abs_link = _entry_link(entry, rel="alternate") or getattr(entry, "link", None)
        arxiv_id, version = extract_arxiv_id(abs_link)

    if not arxiv_id:
        return None

    title = " ".join(str(getattr(entry, "title", "") or "").split())
    if not title:
        return None

    summary = " ".join(str(getattr(entry, "summary", "") or "").split()) or None
    published = _date_only(getattr(entry, "published", None))
    updated = _date_only(getattr(entry, "updated", None))
    authors = _entry_authors(entry)
    categories = _entry_categories(entry)
    pdf_url = _entry_link(entry, title="pdf") or _entry_link(entry, rel="related")
    entry_url = (
        _entry_link(entry, rel="alternate")
        or getattr(entry, "link", None)
        or f"https://arxiv.org/abs/{arxiv_id}"
    )
    version_text = str(version).strip() if version else None

    return {
        "result_id": f"arxiv:{arxiv_id}",
        "result_type": "work",
        "source": "arxiv",
        "source_id": arxiv_id,
        "arxiv_id": arxiv_id,
        "arxiv_version": version_text,
        "openalex_id": None,
        "title": title,
        "summary": summary,
        "publication_year": _year_from_date(published) or _year_from_date(updated),
        "publication_date": published,
        "updated_date": updated,
        "authors": authors,
        "primary_source": "arXiv",
        "journal": "arXiv",
        "doi": None,
        "work_type": "preprint",
        "cited_by_count": None,
        "citation_count": None,
        "is_open_access": True,
        "categories": categories,
        "pdf_url": pdf_url,
        "entry_url": str(entry_url).strip() if entry_url else None,
    }


def parse_arxiv_feed(xml_text: str) -> dict[str, Any]:
    """Parse Atom XML into total_results + normalized work entries."""
    feed = feedparser.parse(xml_text)
    total_raw = None
    if getattr(feed, "feed", None):
        total_raw = feed.feed.get("opensearch_totalresults") or feed.feed.get(
            "opensearch_totalResults"
        )
    try:
        total_results = int(total_raw) if total_raw is not None else None
    except (TypeError, ValueError):
        total_results = None

    works: list[dict[str, Any]] = []
    for entry in getattr(feed, "entries", None) or []:
        normalized = normalize_arxiv_work(entry)
        if normalized is not None:
            works.append(normalized)

    return {
        "total_results": total_results,
        "works": works,
    }


def author_name_matches_query(author_name: str, query: str) -> bool:
    """Conservative match: all query tokens appear in the author name."""
    name_norm = normalize_author_name_for_id(author_name)
    query_norm = normalize_author_name_for_id(query)
    if not name_norm or not query_norm:
        return False
    if name_norm == query_norm:
        return True
    tokens = [tok for tok in query_norm.split(" ") if tok]
    if not tokens:
        return False
    return all(tok in name_norm for tok in tokens)


def aggregate_arxiv_author_names(
    works: list[dict[str, Any]],
    *,
    query: str,
) -> list[dict[str, Any]]:
    """
    Build experimental author-name results from paper metadata.

    Does not claim unique real-world identity.
    """
    buckets: dict[str, dict[str, Any]] = {}

    for work in works:
        authors = work.get("authors") if isinstance(work.get("authors"), list) else []
        for author in authors:
            if not isinstance(author, dict):
                continue
            name = str(author.get("name") or "").strip()
            if not name or not author_name_matches_query(name, query):
                continue

            key = normalize_author_name_for_id(name)
            if not key:
                continue

            bucket = buckets.get(key)
            if bucket is None:
                bucket = {
                    "display_name": name,
                    "key": key,
                    "paper_ids": set(),
                    "sample_papers": [],
                }
                buckets[key] = bucket

            paper_id = work.get("result_id")
            if paper_id and paper_id not in bucket["paper_ids"]:
                bucket["paper_ids"].add(paper_id)
                if len(bucket["sample_papers"]) < 2:
                    bucket["sample_papers"].append(
                        {
                            "result_id": paper_id,
                            "title": work.get("title"),
                            "publication_year": work.get("publication_year"),
                        }
                    )

    results: list[dict[str, Any]] = []
    for bucket in buckets.values():
        results.append(
            {
                "result_id": f"arxiv-author-name:{bucket['key']}",
                "result_type": "author_name",
                "source": "arxiv",
                "display_name": bucket["display_name"],
                "is_verified_profile": False,
                "identity_type": "paper_metadata_name",
                "matching_papers_count": len(bucket["paper_ids"]),
                "sample_papers": bucket["sample_papers"],
                "primary_institution": None,
                "topics": [],
                "works_count": None,
                "cited_by_count": None,
                "orcid": None,
                "openalex_id": None,
            }
        )

    results.sort(
        key=lambda item: (
            -(item.get("matching_papers_count") or 0),
            normalize_author_name_for_id(item.get("display_name") or ""),
        )
    )
    return results
