"""Match degree specialization (e.g. Master's in AI) to job domain."""

from __future__ import annotations

import re
from typing import Literal

from hireability.models import JobPost

DegreeField = Literal[
    "ai",
    "data_science",
    "computer_science",
    "software_engineering",
    "business",
    "design",
    "cybersecurity",
    "general",
]

FIELD_LABELS: dict[DegreeField, str] = {
    "ai": "AI / machine learning",
    "data_science": "data science",
    "computer_science": "computer science",
    "software_engineering": "software engineering",
    "business": "business / MBA",
    "design": "design / UX",
    "cybersecurity": "cybersecurity",
    "general": "general",
}

FIELD_PATTERNS: list[tuple[DegreeField, re.Pattern[str]]] = [
    (
        "ai",
        re.compile(
            r"\b("
            r"artificial intelligence|\bai\b|machine learning|\bml\b|deep learning|"
            r"neural network|nlp|natural language processing|computer vision|"
            r"generative ai|llm|large language model"
            r")\b",
            re.IGNORECASE,
        ),
    ),
    (
        "data_science",
        re.compile(
            r"\b(data science|data scientist|data analytics|analytics engineer|"
            r"business intelligence|\bbi\b)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "cybersecurity",
        re.compile(
            r"\b(cyber\s*security|information security|infosec|security engineer|"
            r"penetration test|soc analyst)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "design",
        re.compile(
            r"\b(ux|ui|product design|graphic design|user experience|user interface|"
            r"visual design)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "business",
        re.compile(
            r"\b(mba|business administration|marketing manager|product marketing|"
            r"sales manager|finance manager|consultant)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "software_engineering",
        re.compile(
            r"\b(software engineer|software developer|full[- ]?stack|backend engineer|"
            r"frontend engineer|devops|sre|platform engineer|web developer)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "computer_science",
        re.compile(
            r"\b(computer science|\bcs\b|computing|information technology|\bit\b|"
            r"b\.?\s?tech|b\.?\s?e\.?|m\.?\s?tech|m\.?\s?e\.?)\b",
            re.IGNORECASE,
        ),
    ),
]

RELATED_FIELDS: dict[DegreeField, set[DegreeField]] = {
    "ai": {"data_science", "computer_science", "software_engineering"},
    "data_science": {"ai", "computer_science", "software_engineering"},
    "computer_science": {"ai", "data_science", "software_engineering", "cybersecurity"},
    "software_engineering": {"computer_science", "ai", "data_science", "cybersecurity"},
    "cybersecurity": {"computer_science", "software_engineering"},
    "design": set(),
    "business": set(),
    "general": set(),
}

FIELD_ALIASES = {
    "ai": "ai",
    "artificial_intelligence": "ai",
    "machine_learning": "ai",
    "ml": "ai",
    "data_science": "data_science",
    "data_scientist": "data_science",
    "computer_science": "computer_science",
    "cs": "computer_science",
    "software_engineering": "software_engineering",
    "software": "software_engineering",
    "engineering": "software_engineering",
    "business": "business",
    "mba": "business",
    "design": "design",
    "ux": "design",
    "cybersecurity": "cybersecurity",
    "security": "cybersecurity",
    "general": "general",
}


def normalize_degree_field(value: str | None) -> DegreeField:
    if not value:
        return "general"
    cleaned = value.strip().lower().replace(".", "").replace("-", "_").replace(" ", "_")
    return FIELD_ALIASES.get(cleaned, "general")  # type: ignore[return-value]


def detect_fields_in_text(text: str) -> list[DegreeField]:
    if not text:
        return []
    found: list[DegreeField] = []
    for field, pattern in FIELD_PATTERNS:
        if pattern.search(text):
            found.append(field)
    return found


def detect_job_field(job: JobPost) -> DegreeField:
    blob = " ".join(
        [job.title, job.description, job.category, " ".join(job.tags)]
    )
    matches = detect_fields_in_text(blob)
    if not matches:
        return "general"
    priority = [
        "ai",
        "data_science",
        "cybersecurity",
        "design",
        "business",
        "software_engineering",
        "computer_science",
    ]
    for field in priority:
        if field in matches:
            return field
    return matches[0]


def infer_degree_field(
    *,
    education_text: str = "",
    role: str = "",
    full_text: str = "",
) -> DegreeField:
    blob = f"{education_text}\n{role}".strip()
    matches = detect_fields_in_text(blob)
    if matches:
        for field in ("ai", "data_science", "computer_science", "software_engineering"):
            if field in matches:
                return field
        return matches[0]

    if re.search(r"\b(master|m\.?\s?sc|m\.?\s?tech|mba|ph\.?d)\b", blob, re.I):
        role_matches = detect_fields_in_text(role or full_text)
        if role_matches:
            return role_matches[0]
    return "general"


def degree_field_fit(
    profile_field: DegreeField,
    job_field: DegreeField,
    *,
    degree_level: str,
) -> float:
    if profile_field == "general" or job_field == "general":
        return 1.0

    level_boost = {
        "doctorate": 1.15,
        "master": 1.12,
        "bachelor": 1.06,
        "associate": 1.03,
    }.get(degree_level, 1.0)

    if profile_field == job_field:
        return level_boost

    if job_field in RELATED_FIELDS.get(profile_field, set()):
        return min(level_boost, 1.05)

    return 0.86


def job_degree_field_weight(
    job: JobPost,
    *,
    degree_field: DegreeField,
    degree_level: str,
) -> float:
    job_field = detect_job_field(job)
    return degree_field_fit(degree_field, job_field, degree_level=degree_level)


def matching_field_share(
    jobs: list[JobPost],
    *,
    degree_field: DegreeField,
    degree_level: str,
) -> float:
    if not jobs or degree_field == "general":
        return 1.0
    matches = sum(
        1
        for job in jobs
        if degree_field_fit(
            degree_field,
            detect_job_field(job),
            degree_level=degree_level,
        )
        >= 1.0
    )
    return matches / len(jobs)


def field_label(field: DegreeField) -> str:
    return FIELD_LABELS.get(field, field)
