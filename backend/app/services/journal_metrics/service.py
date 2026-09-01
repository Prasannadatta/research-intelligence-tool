"""Journal metrics cache: ISSN lookup, Elsevier fetch, batch upsert."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.issn import compact_issn, format_issn
from app.db.models.journal_metrics import JournalIssnAlias, JournalMetrics
from app.integrations.elsevier.client import ElsevierClient, elsevier_configured
from app.integrations.elsevier.serial_title import (
    SerialTitleMetrics,
    fetch_serial_title_metrics,
)

logger = logging.getLogger(__name__)

FetchFn = Callable[[str], Awaitable[SerialTitleMetrics]]

_http_during_transaction = False


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ttl_for_status(status: str) -> timedelta:
    settings = get_settings()
    if status == "success":
        days = settings.journal_metrics_success_ttl_days
    else:
        days = settings.journal_metrics_negative_ttl_days
    return timedelta(days=max(int(days), 1))


def _is_fresh(row: JournalMetrics, *, now: datetime | None = None) -> bool:
    moment = now or utc_now()
    if row.expires_at is None:
        return False
    expires = row.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return expires > moment


def metrics_payload(row: JournalMetrics | None) -> dict[str, Any] | None:
    """Public Insights payload. Negative-cache rows serialize as null."""
    if row is None or row.status != "success":
        return None
    return {
        "citescore": row.citescore,
        "citescore_year": row.citescore_year,
        "sjr": row.sjr,
        "sjr_year": row.sjr_year,
        "snip": row.snip,
        "snip_year": row.snip_year,
        "source": row.source or "scopus",
        "scopus_url": row.scopus_url,
    }


def reset_http_during_transaction_flag() -> None:
    global _http_during_transaction
    _http_during_transaction = False


def http_ran_during_transaction() -> bool:
    return _http_during_transaction


def display_issn(issn: str | None) -> str | None:
    return format_issn(issn)


class JournalMetricsService:
    """Load cached Scopus journal metrics and enrich missing/stale ISSNs."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        fetch_fn: FetchFn | None = None,
        client: ElsevierClient | None = None,
    ) -> None:
        self.session = session
        self._client = client
        self._fetch_fn = fetch_fn

    async def _fetch(self, issn: str) -> SerialTitleMetrics:
        global _http_during_transaction
        if self.session.in_transaction():
            _http_during_transaction = True
            logger.error("journal_metrics_http_during_sqlite_transaction issn=%s", issn)
        if self._fetch_fn is not None:
            return await self._fetch_fn(issn)
        return await fetch_serial_title_metrics(issn, client=self._client)

    async def get_cached_by_issns(
        self,
        issns: list[str] | set[str],
    ) -> dict[str, JournalMetrics]:
        compact_ids = [value for value in (compact_issn(item) for item in issns) if value]
        if not compact_ids:
            return {}

        alias_result = await self.session.execute(
            select(JournalIssnAlias).where(JournalIssnAlias.normalized_issn.in_(compact_ids))
        )
        aliases = {
            row.normalized_issn: row.journal_metrics_id for row in alias_result.scalars().all()
        }
        metric_ids = set(aliases.values())
        missing = [value for value in compact_ids if value not in aliases]
        if missing:
            direct = await self.session.execute(
                select(JournalMetrics).where(JournalMetrics.normalized_issn.in_(missing))
            )
            for row in direct.scalars().all():
                metric_ids.add(row.id)
                aliases.setdefault(row.normalized_issn, row.id)

        if not metric_ids:
            return {}

        metrics_result = await self.session.execute(
            select(JournalMetrics).where(JournalMetrics.id.in_(metric_ids))
        )
        rows = {row.id: row for row in metrics_result.scalars().all()}
        by_issn: dict[str, JournalMetrics] = {}
        for issn in compact_ids:
            metric_id = aliases.get(issn)
            if metric_id is not None and metric_id in rows:
                by_issn[issn] = rows[metric_id]
        return by_issn

    async def get_or_enrich_metrics(
        self,
        *,
        issn: str,
        journal_name: str | None = None,
    ) -> JournalMetrics | None:
        compact = compact_issn(issn)
        if not compact:
            return None
        mapping = await self.enrich_issns([compact], journal_names={compact: journal_name})
        return mapping.get(compact)

    async def enrich_issns(
        self,
        issns: list[str],
        *,
        journal_names: dict[str, str | None] | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, JournalMetrics]:
        """Return metrics for unique ISSNs, fetching only missing/stale rows.

        HTTP calls run after the cache read transaction is committed. Insights
        callers should pass a bound timeout; cached rows are still returned.
        """
        unique: list[str] = []
        seen: set[str] = set()
        for value in issns:
            compact = compact_issn(value)
            if not compact or compact in seen:
                continue
            seen.add(compact)
            unique.append(compact)
        if not unique:
            return {}

        cached = await self.get_cached_by_issns(unique)
        if self.session.in_transaction():
            await self.session.commit()

        now = utc_now()
        fresh = {issn: row for issn, row in cached.items() if _is_fresh(row, now=now)}
        stale = [issn for issn in unique if issn not in fresh]
        if not stale:
            return {issn: cached[issn] for issn in unique if issn in cached}

        if not elsevier_configured() and self._fetch_fn is None:
            logger.info(
                "journal_metrics_skip_http reason=no_elsevier_api_key stale_count=%s",
                len(stale),
            )
            return {issn: cached[issn] for issn in unique if issn in cached}

        names = journal_names or {}
        settings = get_settings()
        bound = (
            timeout_seconds
            if timeout_seconds is not None
            else settings.journal_metrics_enrichment_timeout_seconds
        )
        concurrency = max(int(settings.elsevier_rate_limit_concurrency), 1)
        deadline = time.monotonic() + max(float(bound), 0.1)

        async def _one(issn: str) -> tuple[str, SerialTitleMetrics]:
            try:
                result = await self._fetch(issn)
            except Exception as exc:  # noqa: BLE001 — enrichment must not fail Insights
                logger.warning(
                    "journal_metrics_fetch_failed issn=%s error=%s",
                    issn,
                    type(exc).__name__,
                )
                result = SerialTitleMetrics(status="error")
            return issn, result

        remaining = list(stale)
        first_wave = True
        timed_out = False
        while remaining:
            time_left = deadline - time.monotonic()
            if time_left <= 0:
                timed_out = True
                break

            cached = await self.get_cached_by_issns(remaining)
            if self.session.in_transaction():
                await self.session.commit()
            now = utc_now()
            remaining = [
                issn
                for issn in remaining
                if not (issn in cached and _is_fresh(cached[issn], now=now))
            ]
            if not remaining:
                break

            batch_size = 1 if first_wave else min(concurrency, len(remaining))
            first_wave = False
            batch = remaining[:batch_size]
            fetched: dict[str, SerialTitleMetrics] = {}
            tasks = [asyncio.create_task(_one(issn)) for issn in batch]
            try:
                done, pending = await asyncio.wait(tasks, timeout=max(time_left, 0.01))
                for task in pending:
                    task.cancel()
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)
                    timed_out = True
                for task in done:
                    try:
                        issn, parsed = task.result()
                    except Exception:  # noqa: BLE001
                        continue
                    fetched[issn] = parsed
            except Exception:
                logger.warning("journal_metrics_enrichment_failed", exc_info=True)
                break

            covered = set(batch)
            for parsed in fetched.values():
                covered.update(parsed.all_issns)
            if fetched:
                await self._upsert_fetched(fetched, journal_names=names)
            remaining = [issn for issn in remaining if issn not in covered]
            if timed_out:
                break

        if timed_out:
            logger.info(
                "journal_metrics_enrichment_timeout timeout_s=%s remaining=%s",
                bound,
                len(remaining),
            )

        cached = await self.get_cached_by_issns(unique)
        if self.session.in_transaction():
            await self.session.commit()
        return {issn: cached[issn] for issn in unique if issn in cached}

    async def _upsert_fetched(
        self,
        fetched: dict[str, SerialTitleMetrics],
        *,
        journal_names: dict[str, str | None],
    ) -> None:
        now = utc_now()
        related_issns: set[str] = set(fetched.keys())
        for parsed in fetched.values():
            related_issns.update(parsed.all_issns)

        existing = await self.get_cached_by_issns(related_issns)
        source_index: dict[str, JournalMetrics] = {}
        for row in existing.values():
            if row.scopus_source_id:
                source_index[str(row.scopus_source_id)] = row

        for issn, parsed in fetched.items():
            row = existing.get(issn)
            if row is None and parsed.scopus_source_id:
                row = source_index.get(str(parsed.scopus_source_id))
            if row is None:
                for alias in parsed.all_issns:
                    row = existing.get(alias)
                    if row is not None:
                        break
            if row is None:
                row = JournalMetrics(
                    id=uuid.uuid4(),
                    normalized_issn=issn,
                    source="scopus",
                )
                self.session.add(row)
                await self.session.flush()

            canonical = (
                compact_issn(parsed.print_issn)
                or compact_issn(parsed.electronic_issn)
                or issn
            )
            if canonical:
                row.normalized_issn = canonical
            row.print_issn = parsed.print_issn or row.print_issn
            row.electronic_issn = parsed.electronic_issn or row.electronic_issn
            row.journal_name = parsed.journal_name or journal_names.get(issn) or row.journal_name
            row.scopus_source_id = parsed.scopus_source_id or row.scopus_source_id
            row.scopus_url = parsed.scopus_url or row.scopus_url
            if parsed.status == "success":
                row.citescore = parsed.citescore
                row.citescore_year = parsed.citescore_year
                row.sjr = parsed.sjr
                row.sjr_year = parsed.sjr_year
                row.snip = parsed.snip
                row.snip_year = parsed.snip_year
            row.source = "scopus"
            row.status = parsed.status or "error"
            row.retrieved_at = now
            row.updated_at = now
            row.expires_at = now + _ttl_for_status(row.status)
            row.raw_metadata = parsed.raw_entry
            existing[issn] = row
            if row.scopus_source_id:
                source_index[str(row.scopus_source_id)] = row
            await self._ensure_aliases(row, [issn, *parsed.all_issns])

        await self.session.commit()

    async def _ensure_aliases(self, row: JournalMetrics, issns: list[str]) -> None:
        wanted: list[str] = []
        seen: set[str] = set()
        for value in issns:
            compact = compact_issn(value)
            if compact and compact not in seen:
                seen.add(compact)
                wanted.append(compact)
        if not wanted:
            return
        result = await self.session.execute(
            select(JournalIssnAlias).where(JournalIssnAlias.normalized_issn.in_(wanted))
        )
        have = {alias.normalized_issn: alias for alias in result.scalars().all()}
        for compact in wanted:
            alias = have.get(compact)
            if alias is None:
                self.session.add(
                    JournalIssnAlias(
                        id=uuid.uuid4(),
                        normalized_issn=compact,
                        journal_metrics_id=row.id,
                    )
                )
            elif alias.journal_metrics_id != row.id:
                alias.journal_metrics_id = row.id
