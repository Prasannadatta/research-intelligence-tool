"""Diagnose Elsevier Serial Title access for a journal ISSN.

Usage (from the backend/ directory):

    python -m app.scripts.test_elsevier_journal_metrics --issn 1050-2947
"""

from __future__ import annotations

import argparse
import asyncio
import sys


def _yes_no(value: str | None) -> str:
    return "yes" if (value or "").strip() else "no"


async def _run(issn: str) -> int:
    from app.core.config import get_settings
    from app.core.issn import compact_issn, format_issn
    from app.integrations.elsevier.serial_title import fetch_serial_title_metrics

    settings = get_settings()
    compact = compact_issn(issn)
    print(f"ISSN input: {issn}")
    print(f"ISSN normalized: {format_issn(compact) or compact or '(invalid)'}")
    print(f"API key found: {_yes_no(settings.elsevier_api_key)}")
    print(f"Institutional token found: {_yes_no(settings.elsevier_inst_token)}")
    if not compact:
        print("Status: invalid ISSN")
        return 2
    if not (settings.elsevier_api_key or "").strip():
        print("HTTP status: (not sent)")
        print("Set ELSEVIER_API_KEY in backend/.env and retry.")
        return 1

    metrics = await fetch_serial_title_metrics(compact)
    print(f"HTTP status: {metrics.http_status if metrics.http_status is not None else '(none)'}")
    print(f"View used: {metrics.view_used or '(none)'}")
    print(f"Cache/status class: {metrics.status}")
    print(f"Journal title: {metrics.journal_name or '(none)'}")
    print(
        "Metrics returned: "
        f"CiteScore={metrics.citescore if metrics.citescore is not None else '—'} "
        f"({metrics.citescore_year or '—'}), "
        f"SJR={metrics.sjr if metrics.sjr is not None else '—'} "
        f"({metrics.sjr_year or '—'}), "
        f"SNIP={metrics.snip if metrics.snip is not None else '—'} "
        f"({metrics.snip_year or '—'})"
    )
    if metrics.scopus_url:
        print(f"Scopus URL: {metrics.scopus_url}")
    if metrics.entitlement_error:
        print(f"Entitlement/access error: {metrics.entitlement_error}")
    return 0 if metrics.status == "success" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Test Elsevier Serial Title journal-metrics access for one ISSN."
    )
    parser.add_argument("--issn", required=True, help="Journal ISSN, e.g. 1050-2947")
    args = parser.parse_args(argv)
    return asyncio.run(_run(args.issn))


if __name__ == "__main__":
    sys.exit(main())
