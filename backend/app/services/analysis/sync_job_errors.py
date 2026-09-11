"""Shared incomplete/rate-limit failure payloads for analysis background jobs."""

from __future__ import annotations

from typing import Any, Literal

from app.services.analysis.author_work_sync import STATUS_COMPLETE, STATUS_FAILED, STATUS_PARTIAL

JobContext = Literal["insights", "publication_stats"]


def _is_verified_complete(row: dict[str, Any]) -> bool:
    status = str(row.get("status") or "").lower()
    if status not in {STATUS_COMPLETE, "fresh", "success"}:
        return False
    # Missing coverage_verified must NOT default to True.
    return bool(row.get("coverage_verified")) is True


def rate_limit_failure(stats: list[dict[str, Any]]) -> dict[str, Any] | None:
    limited = [row for row in stats if row.get("rate_limited")]
    if not limited:
        return None
    providers = sorted(
        {
            str(row.get("provider") or "provider").strip().lower()
            for row in limited
            if row.get("provider")
        }
    )
    provider = providers[0] if len(providers) == 1 else "provider"
    label = {
        "openalex": "OpenAlex",
        "arxiv": "arXiv",
    }.get(provider, provider[:1].upper() + provider[1:] if provider else "Provider")
    message = (
        f"{label} rate limit reached. Your existing data is safe; please try again shortly."
    )
    return {
        "rate_limited": True,
        "provider": provider if provider != "provider" else None,
        "providers": providers,
        "error_message": message,
        "sync_status": STATUS_PARTIAL,
    }


def _format_problem_parts(problems: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for row in problems:
        name = row.get("display_name") or row.get("canonical_author_id") or "Selected author"
        provider = row.get("provider") or "provider"
        status = row.get("status") or STATUS_FAILED
        detail = row.get("error_message")
        if detail:
            parts.append(f"{name} ({provider}): {status} — {detail}")
        else:
            parts.append(f"{name} ({provider}): {status}")
    joined = "; ".join(parts[:3])
    if len(parts) > 3:
        joined = f"{joined}; +{len(parts) - 3} more"
    return joined


def _blocking_sync_problems(stats: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return sync rows that block a verified-complete analytics job.

    OpenAlex is the source of truth for verified completeness. Name-based arXiv
    enrichment must not falsely certify a corpus, and must not permanently block
    an otherwise verified OpenAlex corpus unless arXiv hard-failed with no OA.
    """
    if not stats:
        return [
            {
                "display_name": "Selected authors",
                "provider": None,
                "status": STATUS_FAILED,
                "error_message": (
                    "No provider sync results were produced for the selected authors."
                ),
            }
        ]

    by_author: dict[str, list[dict[str, Any]]] = {}
    for row in stats:
        author_id = str(row.get("canonical_author_id") or "").strip() or "_unknown"
        by_author.setdefault(author_id, []).append(row)

    problems: list[dict[str, Any]] = []
    for author_rows in by_author.values():
        openalex_rows = [
            row
            for row in author_rows
            if str(row.get("provider") or "").lower() == "openalex"
        ]
        arxiv_rows = [
            row for row in author_rows if str(row.get("provider") or "").lower() == "arxiv"
        ]
        other_rows = [
            row
            for row in author_rows
            if str(row.get("provider") or "").lower() not in {"openalex", "arxiv"}
            or row.get("provider") is None
        ]

        if openalex_rows:
            for row in openalex_rows:
                if not _is_verified_complete(row):
                    problems.append(row)
            continue

        # No OpenAlex identity: cannot certify a complete corpus.
        if arxiv_rows or other_rows:
            source = (arxiv_rows or other_rows)[0]
            problems.append(
                {
                    **source,
                    "status": STATUS_FAILED,
                    "error_message": (
                        source.get("error_message")
                        or "Verified complete analytics require a linked OpenAlex identity."
                    ),
                    "coverage_verified": False,
                }
            )
            continue

        problems.extend(author_rows)

    return problems


def _incomplete_message(problems: list[dict[str, Any]], *, context: JobContext) -> str:
    joined = _format_problem_parts(problems)
    if context == "insights":
        return (
            "Publication coverage is incomplete for the selected authors, "
            f"so Collaboration Insights cannot be marked complete. {joined}"
        )
    return (
        "Complete publication statistics are unavailable because coverage sync "
        f"did not finish. {joined}"
    )


def incomplete_sync_failure(
    stats: list[dict[str, Any]],
    *,
    context: JobContext,
) -> dict[str, Any] | None:
    rate_limit = rate_limit_failure(stats)
    if rate_limit:
        return rate_limit
    problems = _blocking_sync_problems(stats)
    if not problems:
        return None
    return {
        "rate_limited": False,
        "provider": None,
        "providers": [],
        "error_message": _incomplete_message(problems, context=context),
        "sync_status": STATUS_FAILED,
    }
