"""Grant-number normalization and auto-detection heuristics."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class NormalizedGrantNumber:
    original: str
    normalized: str
    compact: str


_SPACE_RE = re.compile(r"\s+")
_GRANTISH_TOKEN_RE = re.compile(
    r"^[A-Za-z]{0,8}\d[\w./-]*$|^\d[\w./-]*[A-Za-z][\w./-]*$|^\d{4,}([./-]\w+)*$"
)


def normalize_grant_number(value: str | None) -> NormalizedGrantNumber:
    """
    Normalize a grant/award number for lookup.

    Keeps meaningful hyphens and slashes. Does not strip punctuation blindly.
    """
    original = (value or "").strip()
    normalized = _SPACE_RE.sub(" ", original).strip()
    compact = normalized.replace(" ", "")
    return NormalizedGrantNumber(
        original=original,
        normalized=normalized,
        compact=compact,
    )


def looks_like_grant_number(value: str | None) -> bool:
    """
    Conservative auto-detection for grant-like identifiers.

    Ordinary author names and research phrases should return False.
    When uncertain, return False so keyword search is used.
    """
    grant = normalize_grant_number(value)
    text = grant.normalized
    if len(text) < 3:
        return False
    from app.integrations.orcid.normalize import normalize_orcid_id

    if normalize_orcid_id(value):
        return False

    compact = grant.compact
    if not any(ch.isdigit() for ch in compact):
        return False

    # Multi-word alphabetic phrases (e.g. "quantum computing", "john smith")
    tokens = [tok for tok in text.split(" ") if tok]
    alpha_words = [tok for tok in tokens if tok.isalpha() and len(tok) > 1]
    if len(alpha_words) >= 2 and not re.search(r"[-/]", text):
        return False

    # Names like "Alice" with no digits already rejected.
    # Reject pure letter acronyms without digits.
    if compact.isalpha():
        return False

    digit_count = sum(ch.isdigit() for ch in compact)
    letter_count = sum(ch.isalpha() for ch in compact)
    digit_ratio = digit_count / max(len(compact), 1)

    has_separator = bool(re.search(r"[-/_]", compact))
    mixed_alnum = digit_count > 0 and letter_count > 0

    if digit_ratio >= 0.6 and digit_count >= 4:
        return True
    if mixed_alnum and (has_separator or digit_count >= 3):
        return True
    if has_separator and digit_count >= 3:
        return True
    if _GRANTISH_TOKEN_RE.fullmatch(compact):
        return True

    return False


def grant_number_match_rank(candidate_award_id: str | None, grant: NormalizedGrantNumber) -> int:
    """Higher is a better match against the requested grant number."""
    if not candidate_award_id:
        return 0
    left = candidate_award_id.strip()
    variants = {
        grant.normalized,
        grant.compact,
        grant.normalized.upper(),
        grant.compact.upper(),
        grant.normalized.lower(),
        grant.compact.lower(),
    }
    if left in variants or left.upper() in {v.upper() for v in variants}:
        return 100
    left_compact = left.replace(" ", "")
    if left_compact.lower() == grant.compact.lower():
        return 90
    if grant.compact.lower() in left_compact.lower():
        return 40
    return 10
