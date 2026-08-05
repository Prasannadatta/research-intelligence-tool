"""Reusable author name normalization helpers."""

from __future__ import annotations

import re
import unicodedata


_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_SPACE_RE = re.compile(r"\s+")


def strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def normalize_author_name(value: str | None) -> str:
    """
    Comparison key for author names.

    - lowercases
    - removes punctuation
    - normalizes whitespace
    - handles "Last, First" formatting
    - preserves initials as letters
    - strips accents for comparison only
    """
    text = strip_accents(value or "").strip().lower()
    if not text:
        return ""

    if "," in text:
        left, right = text.split(",", 1)
        text = f"{right.strip()} {left.strip()}".strip()

    text = _PUNCT_RE.sub(" ", text)
    text = _SPACE_RE.sub(" ", text).strip()
    return text


def split_surname_and_initial(normalized_name: str) -> tuple[str | None, str | None]:
    tokens = [tok for tok in (normalized_name or "").split(" ") if tok]
    if not tokens:
        return None, None
    surname = tokens[-1]
    first_initial = tokens[0][0] if tokens[0] else None
    return surname or None, first_initial


def names_compatible(a: str, b: str) -> bool:
    """True when names are compatible (not conflicting middle names)."""
    na = normalize_author_name(a)
    nb = normalize_author_name(b)
    if not na or not nb:
        return False
    if na == nb:
        return True

    ta = na.split(" ")
    tb = nb.split(" ")
    if ta[-1] != tb[-1]:
        return False

    # Compare given-name tokens; single-letter initials may match longer forms.
    ga = ta[:-1]
    gb = tb[:-1]
    if not ga or not gb:
        return True

    shorter, longer = (ga, gb) if len(ga) <= len(gb) else (gb, ga)
    for i, token in enumerate(shorter):
        other = longer[i]
        if token == other:
            continue
        if len(token) == 1 and other.startswith(token):
            continue
        if len(other) == 1 and token.startswith(other):
            continue
        return False
    return True
