"""Elsevier / Scopus integrations."""

from app.integrations.elsevier.cited_by import (
    CitingWorkRecord,
    ScopusSearchPage,
    ScopusWorkIds,
    fetch_citing_page,
    parse_citing_entry,
    parse_search_page,
    resolve_scopus_ids_for_doi,
)
from app.integrations.elsevier.client import ElsevierApiError, ElsevierClient, elsevier_configured
from app.integrations.elsevier.serial_title import (
    SerialTitleMetrics,
    fetch_serial_title_metrics,
    parse_serial_title_payload,
)

__all__ = [
    "CitingWorkRecord",
    "ElsevierApiError",
    "ElsevierClient",
    "ScopusSearchPage",
    "ScopusWorkIds",
    "SerialTitleMetrics",
    "elsevier_configured",
    "fetch_citing_page",
    "fetch_serial_title_metrics",
    "parse_citing_entry",
    "parse_search_page",
    "parse_serial_title_payload",
    "resolve_scopus_ids_for_doi",
]
