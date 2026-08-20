"""Infer student status, degree level, and completed-degree signals from resume text."""

from __future__ import annotations

import re
from typing import Literal

DegreeLevel = Literal["none", "associate", "bachelor", "master", "doctorate"]

DEGREE_LEVEL_ORDER: dict[DegreeLevel, int] = {
    "none": 0,
    "associate": 1,
    "bachelor": 2,
    "master": 3,
    "doctorate": 4,
}

EDUCATION_HEADING_RE = re.compile(r"^education\b", re.IGNORECASE)
DEGREE_RE = re.compile(
    r"\b("
    r"b\.?\s?tech|b\.?\s?e\.?|bachelor(?:'s)?|b\.?\s?sc|b\.?\s?a\.?|"
    r"m\.?\s?tech|m\.?\s?e\.?|master(?:'s)?|mba|ph\.?d|doctorate|m\.?\s?sc|"
    r"associate(?:'s)?|diploma"
    r")\b",
    re.IGNORECASE,
)
IN_PROGRESS_RE = re.compile(
    r"\b("
    r"student|pursuing|expected\s+(?:graduation|to\s+graduate)|present|ongoing|"
    r"currently\s+enrolled|in\s+progress|final\s+year|pre[- ]?final|undergraduate"
    r")\b",
    re.IGNORECASE,
)
FUTURE_YEAR_RE = re.compile(r"\b20(2[6-9]|3\d)\b")

DOCTORATE_LEVEL_RE = re.compile(r"\b(ph\.?\s?d\.?|phd|doctorate|doctoral)\b", re.IGNORECASE)
MASTER_LEVEL_RE = re.compile(
    r"\b(master'?s?|m\.?\s?sc\.?|m\.?\s?tech\.?|m\.?\s?e\.?|mba|m\.?\s?a\.?)\b",
    re.IGNORECASE,
)
BACHELOR_LEVEL_RE = re.compile(
    r"\b(bachelor'?s?|b\.?\s?tech\.?|b\.?\s?e\.?|b\.?\s?sc\.?|b\.?\s?a\.?|be\b)\b",
    re.IGNORECASE,
)
ASSOCIATE_LEVEL_RE = re.compile(r"\b(associate'?s?|diploma|hnd)\b", re.IGNORECASE)

LEVEL_ALIASES = {
    "none": "none",
    "associate": "associate",
    "diploma": "associate",
    "bachelor": "bachelor",
    "bachelors": "bachelor",
    "bsc": "bachelor",
    "btech": "bachelor",
    "bs": "bachelor",
    "ba": "bachelor",
    "be": "bachelor",
    "undergraduate": "bachelor",
    "master": "master",
    "masters": "master",
    "msc": "master",
    "mtech": "master",
    "ms": "master",
    "mba": "master",
    "postgraduate": "master",
    "doctorate": "doctorate",
    "doctoral": "doctorate",
    "phd": "doctorate",
    "ph.d": "doctorate",
}


def _education_text(sections: dict[str, str]) -> str:
    for heading, body in sections.items():
        if EDUCATION_HEADING_RE.match(heading):
            return body
    return ""


def infer_education_status(
    *,
    sections: dict[str, str] | None = None,
    full_text: str = "",
    has_work_experience: bool = False,
    role: str = "",
) -> tuple[bool, bool]:
    """
    Return (is_student, has_degree).

    Students are assumed to have less bandwidth to upskill quickly.
    Completed degrees plus employment signal faster skill acquisition.
    """
    sections = sections or {}
    education = _education_text(sections)
    blob = f"{education}\n{role}".strip()

    has_degree_mention = bool(DEGREE_RE.search(education or full_text))
    in_progress = bool(IN_PROGRESS_RE.search(blob))
    if education and re.search(r"\b(present|current|expected)\b", education, re.IGNORECASE):
        in_progress = True
    if education and FUTURE_YEAR_RE.search(education) and not has_work_experience:
        in_progress = True

    is_student = in_progress
    has_degree = has_degree_mention and not in_progress

    # Post-grad student: completed bachelor's, pursuing master's.
    if in_progress and education and re.search(
        r"\b(bachelor|b\.?\s?tech|b\.?\s?sc)\b.*\b(master|m\.?\s?tech|mba|ph\.?d)\b",
        education,
        re.IGNORECASE | re.DOTALL,
    ):
        has_degree = True

    if "student" in role.lower():
        is_student = True

    return is_student, has_degree


def _highest_degree_in_text(text: str) -> DegreeLevel:
    levels: list[DegreeLevel] = []
    if DOCTORATE_LEVEL_RE.search(text):
        levels.append("doctorate")
    if MASTER_LEVEL_RE.search(text):
        levels.append("master")
    if BACHELOR_LEVEL_RE.search(text):
        levels.append("bachelor")
    if ASSOCIATE_LEVEL_RE.search(text):
        levels.append("associate")
    if not levels:
        return "none"
    return max(levels, key=lambda level: DEGREE_LEVEL_ORDER[level])


def normalize_degree_level(value: str | None) -> DegreeLevel:
    if not value:
        return "none"
    cleaned = value.strip().lower().replace(".", "").replace(" ", "_").replace("-", "_")
    return LEVEL_ALIASES.get(cleaned, "none")  # type: ignore[return-value]


def infer_degree_level(
    *,
    sections: dict[str, str] | None = None,
    full_text: str = "",
    is_student: bool = False,
    has_degree: bool = False,
) -> DegreeLevel:
    sections = sections or {}
    education = _education_text(sections)
    blob = education or full_text
    detected = _highest_degree_in_text(blob)

    if has_degree and detected == "none":
        return "bachelor"
    if is_student and detected != "none":
        return detected
    if has_degree:
        return detected
    return "none"


def parse_degree_level(
    raw: dict,
    *,
    sections: dict[str, str] | None = None,
    full_text: str = "",
    is_student: bool = False,
    has_degree: bool = False,
) -> DegreeLevel:
    if raw.get("degree_level"):
        return normalize_degree_level(str(raw["degree_level"]))

    education = raw.get("education")
    if isinstance(education, dict) and education.get("degree"):
        return normalize_degree_level(str(education["degree"]))

    return infer_degree_level(
        sections=sections,
        full_text=str(raw.get("resume_text", "")) or full_text,
        is_student=is_student,
        has_degree=has_degree,
    )


def parse_education_flags(
    raw: dict,
    *,
    sections: dict[str, str] | None = None,
    full_text: str = "",
    has_work_experience: bool = False,
    role: str = "",
) -> tuple[bool, bool]:
    if "is_student" in raw:
        is_student = bool(raw["is_student"])
    else:
        education = raw.get("education")
        if isinstance(education, dict) and education.get("status"):
            is_student = str(education["status"]).strip().lower() == "student"
        else:
            is_student, _ = infer_education_status(
                sections=sections,
                full_text=str(raw.get("resume_text", "")) or full_text,
                has_work_experience=has_work_experience,
                role=role,
            )

    if "has_degree" in raw:
        has_degree = bool(raw["has_degree"])
    else:
        education = raw.get("education")
        if isinstance(education, dict) and education.get("status"):
            has_degree = str(education["status"]).strip().lower() == "graduate"
        elif "is_student" in raw or (
            isinstance(education, dict) and education.get("status")
        ):
            _, inferred_degree = infer_education_status(
                sections=sections,
                full_text=str(raw.get("resume_text", "")) or full_text,
                has_work_experience=has_work_experience,
                role=role,
            )
            has_degree = inferred_degree
        else:
            _, has_degree = infer_education_status(
                sections=sections,
                full_text=str(raw.get("resume_text", "")) or full_text,
                has_work_experience=has_work_experience,
                role=role,
            )

    return is_student, has_degree


def parse_degree_field(
    raw: dict,
    *,
    sections: dict[str, str] | None = None,
    full_text: str = "",
    role: str = "",
) -> str:
    if raw.get("degree_field"):
        from hireability.jobs.degree_field import normalize_degree_field

        return normalize_degree_field(str(raw["degree_field"]))

    education = raw.get("education")
    if isinstance(education, dict) and education.get("field"):
        from hireability.jobs.degree_field import normalize_degree_field

        return normalize_degree_field(str(education["field"]))

    from hireability.jobs.degree_field import infer_degree_field

    education = _education_text(sections or {})
    return infer_degree_field(
        education_text=education or str(raw.get("resume_text", "")),
        role=role,
        full_text=full_text or str(raw.get("resume_text", "")),
    )
