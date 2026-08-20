"""Detect degree requirements in job posts and score candidate fit."""

from __future__ import annotations

import re
from typing import Literal

from hireability.models import JobPost

DegreeLevel = Literal["none", "associate", "bachelor", "master", "doctorate"]

DEGREE_LEVEL_ORDER: dict[DegreeLevel, int] = {
    "none": 0,
    "associate": 1,
    "bachelor": 2,
    "master": 3,
    "doctorate": 4,
}

DOCTORATE_RE = re.compile(r"\b(ph\.?\s?d\.?|phd|doctorate|doctoral)\b", re.IGNORECASE)
MASTER_RE = re.compile(
    r"\b(master'?s?|m\.?\s?sc\.?|m\.?\s?tech\.?|m\.?\s?e\.?|mba|m\.?\s?a\.?|"
    r"graduate degree|post[- ]?graduate)\b",
    re.IGNORECASE,
)
BACHELOR_RE = re.compile(
    r"\b(bachelor'?s?|b\.?\s?sc\.?|b\.?\s?tech\.?|b\.?\s?e\.?|b\.?\s?a\.?|"
    r"undergraduate degree|undergraduate|bs\b|ba\b|be\b)\b",
    re.IGNORECASE,
)
ASSOCIATE_RE = re.compile(r"\b(associate'?s?|diploma|hnd|a\.?\s?a\.?)\b", re.IGNORECASE)
GENERIC_DEGREE_RE = re.compile(
    r"\b("
    r"degree required|must have (?:a )?degree|requires? (?:a )?degree|"
    r"university degree|college degree|academic degree|"
    r"bachelor'?s? degree required|master'?s? degree required"
    r")\b",
    re.IGNORECASE,
)
def _job_text(job: JobPost) -> str:
    return " ".join(
        [
            job.title,
            job.description,
            job.category,
            " ".join(job.tags),
        ]
    )


def _highest_level_in_text(text: str) -> DegreeLevel | None:
    levels: list[DegreeLevel] = []
    if DOCTORATE_RE.search(text):
        levels.append("doctorate")
    if MASTER_RE.search(text):
        levels.append("master")
    if BACHELOR_RE.search(text):
        levels.append("bachelor")
    if ASSOCIATE_RE.search(text):
        levels.append("associate")

    if not levels:
        return None
    return max(levels, key=lambda level: DEGREE_LEVEL_ORDER[level])


def job_required_degree_level(job: JobPost) -> DegreeLevel | None:
    """Return the highest explicit degree requirement, if any."""
    blob = _job_text(job)
    explicit = _highest_level_in_text(blob)
    if explicit:
        return explicit

    if GENERIC_DEGREE_RE.search(blob):
        return "bachelor"

    # Short forms in titles like "Backend Engineer (BSc)"
    title_only = _highest_level_in_text(job.title)
    if title_only:
        return title_only

    return None


def degree_requirement_fit(
    candidate_level: DegreeLevel,
    required_level: DegreeLevel | None,
    *,
    is_student: bool,
    has_degree: bool = False,
) -> float:
    if required_level is None:
        return 1.0

    candidate_rank = DEGREE_LEVEL_ORDER.get(candidate_level, 0)
    required_rank = DEGREE_LEVEL_ORDER[required_level]

    # Completed degree at or above the bar.
    if candidate_rank > required_rank:
        return 1.0
    if candidate_rank == required_rank and not is_student:
        return 1.0
    if candidate_rank == required_rank and is_student and has_degree:
        return 1.0

    # Actively pursuing the exact required degree — valued, but below a completed one.
    if is_student and candidate_rank == required_rank:
        return 0.82

    gap = required_rank - candidate_rank
    if gap == 1:
        # Pursuing one step below (e.g. bachelor's student for master's role).
        return 0.72 if is_student else 0.40
    if is_student:
        # Student on a different track or early in studies.
        return 0.35 if candidate_rank > 0 else 0.50
    return 0.15


def job_degree_weight(
    job: JobPost,
    *,
    degree_level: DegreeLevel,
    is_student: bool,
    has_degree: bool = False,
) -> float:
    required = job_required_degree_level(job)
    return degree_requirement_fit(
        degree_level,
        required,
        is_student=is_student,
        has_degree=has_degree,
    )


def matching_degree_share(
    jobs: list[JobPost],
    *,
    degree_level: DegreeLevel,
    is_student: bool,
    has_degree: bool = False,
) -> float:
    if not jobs:
        return 1.0

    qualifying = 0
    for job in jobs:
        required = job_required_degree_level(job)
        if required is None:
            qualifying += 1
            continue
        if (
            degree_requirement_fit(
                degree_level,
                required,
                is_student=is_student,
                has_degree=has_degree,
            )
            >= 0.5
        ):
            qualifying += 1
    return qualifying / len(jobs)


def degree_fit_note(
    *,
    degree_level: DegreeLevel,
    is_student: bool,
    has_degree: bool,
) -> str:
    if is_student and not has_degree:
        return f"pursuing {degree_level_label(degree_level)}"
    if has_degree:
        return f"holds {degree_level_label(degree_level)}"
    return degree_level_label(degree_level)


def degree_level_label(level: DegreeLevel) -> str:
    return {
        "none": "no degree",
        "associate": "associate / diploma",
        "bachelor": "bachelor's",
        "master": "master's",
        "doctorate": "doctorate",
    }[level]


def requirement_label(level: DegreeLevel | None) -> str:
    if level is None:
        return "not stated"
    return degree_level_label(level)
