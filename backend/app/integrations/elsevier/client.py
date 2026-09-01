"""Elsevier API HTTP client for Serial Title, Abstract Retrieval, and Scopus Search."""

from __future__ import annotations

import logging

import httpx

from app.core.config import get_settings
from app.core.issn import compact_issn
from app.integrations.rate_limited_http import provider_get

logger = logging.getLogger(__name__)

SERIAL_TITLE_VIEWS = ("CITESCORE", "STANDARD", "ENHANCED")
REQUEST_TIMEOUT_SECONDS = 12.0


class ElsevierApiError(Exception):
    """Raised for Elsevier authentication, entitlement, or transport failures."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 502,
        entitlement: bool = False,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.entitlement = entitlement
        self.retryable = retryable


def elsevier_headers(*, api_key: str | None = None, inst_token: str | None = None) -> dict[str, str]:
    """Build Elsevier headers. Institutional token is omitted when unset."""
    settings = get_settings()
    key = (api_key if api_key is not None else settings.elsevier_api_key) or ""
    key = key.strip()
    token = inst_token if inst_token is not None else settings.elsevier_inst_token
    token = (token or "").strip()
    headers = {
        "X-ELS-APIKey": key,
        "Accept": "application/json",
    }
    if token:
        headers["X-ELS-Insttoken"] = token
    return headers


def elsevier_configured() -> bool:
    return bool((get_settings().elsevier_api_key or "").strip())


class ElsevierClient:
    """Thin Elsevier HTTP wrapper. Never logs API keys or institutional tokens."""

    def __init__(self, *, request_func=provider_get) -> None:
        self._request_func = request_func

    def _require_api_key(self) -> str:
        api_key = (get_settings().elsevier_api_key or "").strip()
        if not api_key:
            raise ElsevierApiError(
                "Elsevier API key is not configured. Set ELSEVIER_API_KEY in the backend environment.",
                status_code=500,
            )
        return api_key

    async def get_serial_title(
        self,
        issn: str,
        *,
        view: str = "CITESCORE",
    ) -> httpx.Response:
        compact = compact_issn(issn)
        if not compact:
            raise ElsevierApiError(f"Invalid ISSN: {issn}", status_code=400)
        self._require_api_key()
        settings = get_settings()
        base = settings.elsevier_serial_title_base_url.rstrip("/")
        url = f"{base}/issn/{compact}"
        headers = elsevier_headers()
        logger.info(
            "elsevier_serial_title issn=%s view=%s inst_token=%s",
            compact,
            view,
            "yes" if (settings.elsevier_inst_token or "").strip() else "no",
        )
        return await self._request_func(
            "elsevier",
            url,
            params={"view": view},
            headers=headers,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

    async def get_abstract_doi(self, doi: str, *, view: str = "META") -> httpx.Response:
        """Abstract Retrieval. Use view=META only; FULL/REF are not entitled."""
        from urllib.parse import quote

        cleaned = str(doi or "").strip()
        if not cleaned:
            raise ElsevierApiError("DOI is required.", status_code=400)
        self._require_api_key()
        base = get_settings().elsevier_api_base_url.rstrip("/")
        url = f"{base}/content/abstract/doi/{quote(cleaned, safe='')}"
        return await self._request_func(
            "elsevier",
            url,
            params={"view": view},
            headers=elsevier_headers(),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

    async def search_scopus(
        self,
        query: str,
        *,
        start: int = 0,
        count: int = 25,
    ) -> httpx.Response:
        """Scopus Search. Callers must not pass field= for REF cited-by queries."""
        cleaned = " ".join(str(query or "").split())
        if not cleaned:
            raise ElsevierApiError("Query is required.", status_code=400)
        self._require_api_key()
        page_size = max(1, min(int(count or 25), 25))
        offset = max(int(start or 0), 0)
        base = get_settings().elsevier_api_base_url.rstrip("/")
        url = f"{base}/content/search/scopus"
        return await self._request_func(
            "elsevier",
            url,
            params={"query": cleaned, "start": str(offset), "count": str(page_size)},
            headers=elsevier_headers(),
            timeout=20.0,
        )


def classify_elsevier_status(status_code: int) -> str:
    """Map HTTP status to a journal_metrics status value."""
    if status_code == 200:
        return "success"
    if status_code == 404:
        return "not_found"
    if status_code in {401, 403}:
        return "unavailable"
    return "error"


def entitlement_message(status_code: int) -> str | None:
    if status_code == 401:
        return "Elsevier rejected the request (401). Check ELSEVIER_API_KEY."
    if status_code == 403:
        return (
            "Elsevier entitlement/authorization failed (403). "
            "The API key may lack Serial Title access, or a campus IP / "
            "ELSEVIER_INST_TOKEN may be required."
        )
    if status_code == 429:
        return "Elsevier quota exceeded (429)."
    return None


async def request_serial_title_with_view_fallback(
    issn: str,
    *,
    client: ElsevierClient | None = None,
) -> tuple[httpx.Response, str]:
    """Try CITESCORE, then STANDARD / ENHANCED when the preferred view is blocked."""
    client = client or ElsevierClient()
    last_response: httpx.Response | None = None
    last_view = SERIAL_TITLE_VIEWS[0]
    for view in SERIAL_TITLE_VIEWS:
        last_view = view
        response = await client.get_serial_title(issn, view=view)
        last_response = response
        if response.status_code == 200:
            return response, view
        if response.status_code in {401, 403}:
            logger.info(
                "elsevier_serial_title_view_blocked issn=%s view=%s status=%s",
                compact_issn(issn),
                view,
                response.status_code,
            )
            continue
        return response, view
    assert last_response is not None
    return last_response, last_view
