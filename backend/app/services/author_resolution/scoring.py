"""Match scoring for author identity resolution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.author_resolution.normalization import (
    names_compatible,
    normalize_author_name,
)


DECISION_AUTO_MERGE = "auto_merge"
DECISION_POSSIBLE_DUPLICATE = "possible_duplicate"
DECISION_SEPARATE = "separate"


@dataclass
class MatchScore:
    total_score: float
    name_score: float = 0.0
    institution_score: float = 0.0
    work_overlap_score: float = 0.0
    coauthor_score: float = 0.0
    decision: str = DECISION_SEPARATE
    reasoning: dict[str, Any] = field(default_factory=dict)


def _institution_keys(institutions: list[Any]) -> set[str]:
    keys: set[str] = set()
    for inst in institutions or []:
        if hasattr(inst, "id") and inst.id:
            keys.add(f"id:{inst.id}".lower())
        if hasattr(inst, "institution_id") and inst.institution_id:
            keys.add(f"id:{inst.institution_id}".lower())
        name = getattr(inst, "name", None) or getattr(inst, "display_name", None)
        if name:
            keys.add(f"name:{normalize_author_name(name)}")
        if isinstance(inst, dict):
            if inst.get("id"):
                keys.add(f"id:{inst['id']}".lower())
            if inst.get("name"):
                keys.add(f"name:{normalize_author_name(inst['name'])}")
    return keys


def normalize_work_id(value: Any, *, id_type: str | None = None) -> str | None:
    """Normalize work identifiers so DOI overlap matches across providers."""
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    kind = (id_type or "").strip().lower()
    if text.startswith("https://doi.org/"):
        text = text[len("https://doi.org/") :]
        kind = "doi"
    elif text.startswith("http://doi.org/"):
        text = text[len("http://doi.org/") :]
        kind = "doi"
    elif text.startswith("doi:"):
        text = text[4:]
        kind = "doi"
    if kind == "doi" or (text.startswith("10.") and "/" in text):
        return f"doi:{text}"
    return text


def expand_work_id_keys(value: Any, *, id_type: str | None = None) -> list[str]:
    canonical = normalize_work_id(value, id_type=id_type)
    if not canonical:
        return []
    keys = {canonical, str(value).strip().lower()}
    if canonical.startswith("doi:"):
        keys.add(canonical[4:])
    return [key for key in keys if key]


def _work_ids(works: list[Any]) -> set[str]:
    ids: set[str] = set()
    for work in works or []:
        if isinstance(work, dict) and work.get("id"):
            ids.update(expand_work_id_keys(work.get("id"), id_type=work.get("id_type")))
            continue
        work_id = getattr(work, "work_id", None)
        work_type = getattr(work, "work_id_type", None)
        if work_id:
            ids.update(expand_work_id_keys(work_id, id_type=work_type))
            continue
        ref_id = getattr(work, "id", None)
        if ref_id:
            ids.update(expand_work_id_keys(ref_id, id_type=work_type))
    return ids


def score_candidate_pair(
    left: Any,
    right: Any,
    *,
    auto_merge_threshold: int,
    possible_duplicate_threshold: int,
) -> MatchScore:
    """
    Score two author candidates / provider records.

    Name+institution alone never auto-merges.
    Conflicting ORCIDs force separate.
    """
    reasoning: dict[str, Any] = {"signals": []}

    left_orcid = (getattr(left, "orcid", None) or "").strip() or None
    right_orcid = (getattr(right, "orcid", None) or "").strip() or None
    if left_orcid and right_orcid and left_orcid != right_orcid:
        return MatchScore(
            total_score=0.0,
            decision=DECISION_SEPARATE,
            reasoning={
                "signals": ["conflicting_orcid"],
                "left_orcid": left_orcid,
                "right_orcid": right_orcid,
            },
        )

    same_orcid = bool(left_orcid and right_orcid and left_orcid == right_orcid)

    left_provider = str(getattr(left, "provider", None) or "").strip().lower()
    right_provider = str(getattr(right, "provider", None) or "").strip().lower()
    left_provider_id = str(getattr(left, "provider_author_id", None) or "").strip()
    right_provider_id = str(getattr(right, "provider_author_id", None) or "").strip()
    # OpenAlex can expose multiple author ids for one ORCID. Keep them separate so
    # corpus sync does not OR-crawl unrelated/duplicate profiles.
    if (
        same_orcid
        and left_provider == "openalex"
        and right_provider == "openalex"
        and left_provider_id
        and right_provider_id
        and left_provider_id != right_provider_id
    ):
        return MatchScore(
            total_score=0.0,
            decision=DECISION_SEPARATE,
            reasoning={
                "signals": ["distinct_openalex_ids_same_orcid"],
                "left_orcid": left_orcid,
                "right_orcid": right_orcid,
                "left_provider_author_id": left_provider_id,
                "right_provider_author_id": right_provider_id,
            },
        )

    name_score = 0.0
    left_name = getattr(left, "normalized_name", None) or normalize_author_name(
        getattr(left, "display_name", "")
    )
    right_name = getattr(right, "normalized_name", None) or normalize_author_name(
        getattr(right, "display_name", "")
    )
    if left_name and right_name:
        if left_name == right_name:
            name_score = 35.0
            reasoning["signals"].append("exact_normalized_name")
        elif names_compatible(
            getattr(left, "display_name", left_name),
            getattr(right, "display_name", right_name),
        ):
            name_score = 22.0
            reasoning["signals"].append("compatible_name_format")
        elif same_orcid:
            reasoning["signals"].append("name_mismatch_ignored_same_orcid")
        else:
            reasoning["signals"].append("incompatible_name")
            return MatchScore(
                total_score=0.0,
                name_score=0.0,
                decision=DECISION_SEPARATE,
                reasoning=reasoning,
            )

    institution_score = 0.0
    left_inst = _institution_keys(getattr(left, "institutions", []) or [])
    right_inst = _institution_keys(getattr(right, "institutions", []) or [])
    shared_institutions = left_inst & right_inst
    if shared_institutions:
        institution_score = 15.0
        reasoning["signals"].append("shared_institution")
        reasoning["shared_institutions"] = sorted(shared_institutions)[:5]

    work_overlap_score = 0.0
    left_works = _work_ids(getattr(left, "works", []) or [])
    right_works = _work_ids(getattr(right, "works", []) or [])
    shared_works = left_works & right_works
    if shared_works:
        # Strong positive evidence — a single shared work ID is enough with a
        # compatible name to clear the auto-merge threshold.
        work_overlap_score = min(60.0, 50.0 + 5.0 * (len(shared_works) - 1))
        reasoning["signals"].append("shared_works")
        reasoning["shared_works"] = sorted(shared_works)[:10]

    coauthor_score = 0.0
    left_co = {
        normalize_author_name(name)
        for name in (getattr(left, "coauthors", []) or [])
        if name
    }
    right_co = {
        normalize_author_name(name)
        for name in (getattr(right, "coauthors", []) or [])
        if name
    }
    shared_co = left_co & right_co
    if shared_co:
        coauthor_score = min(20.0, 8.0 * len(shared_co))
        reasoning["signals"].append("shared_coauthors")

    orcid_bonus = 0.0
    if same_orcid:
        orcid_bonus = 70.0
        reasoning["signals"].append("same_orcid")

    same_provider_record = 0.0
    if (
        getattr(left, "provider", None)
        and getattr(left, "provider", None) == getattr(right, "provider", None)
        and getattr(left, "provider_author_id", None)
        and getattr(left, "provider_author_id", None)
        == getattr(right, "provider_author_id", None)
    ):
        same_provider_record = 100.0
        reasoning["signals"].append("same_provider_record")

    total = min(
        100.0,
        name_score
        + institution_score
        + work_overlap_score
        + coauthor_score
        + orcid_bonus
        + same_provider_record,
    )

    # Safety: name + institution alone cannot auto-merge.
    strong_evidence = bool(
        shared_works
        or same_orcid
        or same_provider_record
        or shared_co
    )
    if (
        total >= auto_merge_threshold
        and not strong_evidence
        and name_score > 0
        and institution_score > 0
    ):
        decision = DECISION_POSSIBLE_DUPLICATE
        reasoning["signals"].append("blocked_name_institution_only_auto_merge")
    elif total >= auto_merge_threshold and strong_evidence:
        decision = DECISION_AUTO_MERGE
    elif total >= possible_duplicate_threshold:
        decision = DECISION_POSSIBLE_DUPLICATE
    else:
        decision = DECISION_SEPARATE

    # Publication-count differences never block a merge.
    left_count = getattr(left, "works_count", None)
    right_count = getattr(right, "works_count", None)
    if left_count is not None and right_count is not None and left_count != right_count:
        reasoning["signals"].append("publication_count_difference_ignored")
        reasoning["works_count"] = {"left": left_count, "right": right_count}

    return MatchScore(
        total_score=total,
        name_score=name_score,
        institution_score=institution_score,
        work_overlap_score=work_overlap_score,
        coauthor_score=coauthor_score,
        decision=decision,
        reasoning=reasoning,
    )
