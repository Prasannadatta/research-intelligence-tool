"""Scopus Serial Title response parsing and fetch helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from app.integrations.elsevier.client import (
    ElsevierApiError,
    ElsevierClient,
    classify_elsevier_status,
    request_serial_title_with_view_fallback,
)
from app.core.issn import compact_issn, format_issn


@dataclass
class SerialTitleMetrics:
    status: str
    http_status: int | None = None
    view_used: str | None = None
    journal_name: str | None = None
    print_issn: str | None = None
    electronic_issn: str | None = None
    scopus_source_id: str | None = None
    scopus_url: str | None = None
    citescore: float | None = None
    citescore_year: int | None = None
    sjr: float | None = None
    sjr_year: int | None = None
    snip: float | None = None
    snip_year: int | None = None
    entitlement_error: str | None = None
    raw_entry: dict[str, Any] | None = None
    all_issns: list[str] = field(default_factory=list)

    @property
    def has_metrics(self) -> bool:
        return any(
            value is not None
            for value in (self.citescore, self.sjr, self.snip)
        )


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        for key in ("$", "#text", "_", "value"):
            if key in value:
                return _text(value.get(key))
        return None
    text = str(value).strip()
    return text or None


def _as_float(value: Any) -> float | None:
    text = _text(value)
    if text is None:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    text = _text(value)
    if text is None:
        return None
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def _year_metric_pairs(container: Any, item_key: str) -> list[tuple[float, int | None]]:
    """Parse SJRList/SNIPList-style ``{"SJR": [{"@year": "2024", "$": "1.2"}]}`` payloads."""
    wrapped = _as_dict(container)
    items = _as_list(wrapped.get(item_key) if wrapped else container)
    pairs: list[tuple[float, int | None]] = []
    for item in items:
        if isinstance(item, dict):
            number = _as_float(item.get("$") or item.get("value") or item.get("#text") or item)
            year = _as_int(
                item.get("@year")
                or item.get("year")
                or item.get("@Year")
            )
        else:
            number = _as_float(item)
            year = None
        if number is not None:
            pairs.append((number, year))
    return pairs


def _latest_year_metric(pairs: list[tuple[float, int | None]]) -> tuple[float | None, int | None]:
    if not pairs:
        return None, None
    dated = [(value, year) for value, year in pairs if year is not None]
    if dated:
        value, year = max(dated, key=lambda row: int(row[1] or 0))
        return value, year
    return pairs[0][0], pairs[0][1]


def _parse_citescore(entry: dict[str, Any]) -> tuple[float | None, int | None]:
    info = _as_dict(
        entry.get("citeScoreYearInfoList")
        or entry.get("citescoreyearinfolist")
        or entry.get("citeScoreYearInfo")
    )
    current = _as_float(
        info.get("citeScoreCurrentMetric")
        or info.get("citescorecurrentmetric")
        or entry.get("citeScoreCurrentMetric")
    )
    current_year = _as_int(
        info.get("citeScoreCurrentMetricYear")
        or info.get("citescorecurrentmetricyear")
        or entry.get("citeScoreCurrentMetricYear")
    )
    if current is not None:
        return current, current_year

    year_infos = _as_list(
        info.get("citeScoreYearInfo")
        or info.get("citescoreyearinfo")
        or entry.get("citeScoreYearInfo")
    )
    best: tuple[float, int | None] | None = None
    for item in year_infos:
        row = _as_dict(item)
        year = _as_int(row.get("@year") or row.get("year"))
        nested = _as_dict(row.get("citeScoreInformationList") or row.get("citeScoreInfo"))
        infos = _as_list(nested.get("citeScoreInfo") or nested.get("citeScore") or item)
        score = None
        for candidate in infos:
            blob = _as_dict(candidate) if not isinstance(candidate, (int, float, str)) else {}
            score = _as_float(
                blob.get("citeScore")
                or blob.get("citescore")
                or candidate
            )
            if score is not None:
                break
        if score is None:
            score = _as_float(row.get("citeScore") or row.get("citescore"))
        if score is None:
            continue
        if best is None or (year or 0) >= (best[1] or 0):
            best = (score, year)
    if best:
        return best
    return None, None


def _scopus_source_id(entry: dict[str, Any]) -> str | None:
    for key in ("source-id", "sourceId", "source_id"):
        text = _text(entry.get(key))
        if text:
            return text.replace("SCOPUS_ID:", "").replace("source-id:", "").strip()
    identifier = _text(entry.get("dc:identifier") or entry.get("prism:doi"))
    if identifier and "source-id:" in identifier.lower():
        return identifier.split(":", 1)[-1].strip()
    return None


def _scopus_url(entry: dict[str, Any], source_id: str | None) -> str | None:
    for link in _as_list(entry.get("link")):
        row = _as_dict(link)
        ref = str(row.get("@ref") or row.get("ref") or row.get("@rel") or "").lower()
        href = _text(row.get("@href") or row.get("href") or row.get("@_fa"))
        if href and ref in {"scopus-source", "scopus", "source", "scopus-source-page"}:
            return href
        if href and "scopus.com/sourceid" in href:
            return href
    if source_id:
        return f"https://www.scopus.com/sourceid/{source_id}"
    return None


def _extract_entry(payload: dict[str, Any]) -> dict[str, Any] | None:
    for key in (
        "serial-metadata-response",
        "serial-title-response",
        "serial-metadata",
    ):
        envelope = payload.get(key)
        if isinstance(envelope, dict):
            payload = envelope
            break
    entries = payload.get("entry")
    if isinstance(entries, list) and entries:
        first = entries[0]
        return first if isinstance(first, dict) else None
    if isinstance(entries, dict):
        return entries
    if "dc:title" in payload or "source-id" in payload or "citeScoreYearInfoList" in payload:
        return payload
    return None


def parse_serial_title_payload(
    payload: Any,
    *,
    http_status: int = 200,
    view_used: str | None = None,
) -> SerialTitleMetrics:
    if not isinstance(payload, dict):
        return SerialTitleMetrics(
            status="error" if http_status == 200 else classify_elsevier_status(http_status),
            http_status=http_status,
            view_used=view_used,
        )
    entry = _extract_entry(payload)
    if not entry:
        return SerialTitleMetrics(
            status="error",
            http_status=http_status,
            view_used=view_used,
        )

    print_issn = format_issn(entry.get("prism:issn") or entry.get("prism:Issn") or entry.get("issn"))
    electronic_issn = format_issn(
        entry.get("prism:eIssn") or entry.get("prism:eissn") or entry.get("eIssn") or entry.get("eissn")
    )
    source_id = _scopus_source_id(entry)
    citescore, citescore_year = _parse_citescore(entry)
    sjr, sjr_year = _latest_year_metric(_year_metric_pairs(entry.get("SJRList") or entry.get("sjrList"), "SJR"))
    if sjr is None:
        sjr, sjr_year = _latest_year_metric(_year_metric_pairs(entry.get("SJR"), "SJR"))
    snip, snip_year = _latest_year_metric(_year_metric_pairs(entry.get("SNIPList") or entry.get("snipList"), "SNIP"))
    if snip is None:
        snip, snip_year = _latest_year_metric(_year_metric_pairs(entry.get("SNIP"), "SNIP"))

    issns = [
        compact
        for compact in (
            compact_issn(print_issn),
            compact_issn(electronic_issn),
        )
        if compact
    ]
    return SerialTitleMetrics(
        status="success",
        http_status=http_status,
        view_used=view_used,
        journal_name=_text(entry.get("dc:title") or entry.get("title")),
        print_issn=print_issn,
        electronic_issn=electronic_issn,
        scopus_source_id=source_id,
        scopus_url=_scopus_url(entry, source_id),
        citescore=citescore,
        citescore_year=citescore_year,
        sjr=sjr,
        sjr_year=sjr_year,
        snip=snip,
        snip_year=snip_year,
        raw_entry={
            "source-id": source_id,
            "dc:title": _text(entry.get("dc:title") or entry.get("title")),
            "prism:issn": print_issn,
            "prism:eIssn": electronic_issn,
            "view": view_used,
        },
        all_issns=issns,
    )


async def fetch_serial_title_metrics(
    issn: str,
    *,
    client: ElsevierClient | None = None,
) -> SerialTitleMetrics:
    """Fetch and parse Serial Title metrics for one ISSN.

    Permanent 4xx responses are not retried here; 429/5xx retries are handled
    by the shared provider HTTP helper.
    """
    try:
        response, view = await request_serial_title_with_view_fallback(issn, client=client)
    except ElsevierApiError as exc:
        return SerialTitleMetrics(
            status="unavailable" if exc.status_code in {401, 403, 500} and "not configured" in str(exc).lower() else "error",
            http_status=exc.status_code,
            entitlement_error=str(exc),
        )
    except httpx.HTTPError as exc:
        return SerialTitleMetrics(
            status="error",
            entitlement_error=str(exc)[:200],
        )

    status = classify_elsevier_status(response.status_code)
    if response.status_code != 200:
        entitlement = None
        if response.status_code in {401, 403, 429}:
            entitlement = {
                401: "Elsevier rejected the request (401). Check ELSEVIER_API_KEY.",
                403: (
                    "Elsevier entitlement/authorization failed (403). "
                    "The API key may lack Serial Title access, or a campus IP / "
                    "ELSEVIER_INST_TOKEN may be required."
                ),
                429: "Elsevier quota exceeded (429).",
            }.get(response.status_code)
        return SerialTitleMetrics(
            status=status,
            http_status=response.status_code,
            view_used=view,
            entitlement_error=entitlement,
        )

    try:
        payload = response.json()
    except ValueError:
        return SerialTitleMetrics(
            status="error",
            http_status=200,
            view_used=view,
        )
    parsed = parse_serial_title_payload(payload, http_status=200, view_used=view)
    if parsed.status == "success" and compact_issn(issn) and compact_issn(issn) not in parsed.all_issns:
        compact = compact_issn(issn)
        if compact:
            parsed.all_issns.append(compact)
    return parsed


# Compatibility aliases used by the service layer and package exports.
SerialTitleMetrics = SerialTitleMetrics
parse_serial_title_payload = parse_serial_title_payload
fetch_serial_title_metrics = fetch_serial_title_metrics
