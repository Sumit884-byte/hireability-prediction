"""Classify job work mode and score fit against a profile preference."""

from __future__ import annotations

import re
from typing import Literal

from hireability.models import JobPost

WorkMode = Literal["remote", "hybrid", "on_site", "unknown"]
WorkPreference = Literal["remote", "hybrid", "on_site", "any"]

REMOTE_SOURCE_DEFAULTS = frozenset({"remotive", "remoteok", "jobicy", "himalayas"})
ONSITE_SOURCE_DEFAULTS = frozenset({"linkedin", "glassdoor"})
INTERNSHIP_SOURCE_DEFAULTS = frozenset({"internshala"})

REMOTE_RE = re.compile(
    r"\b(remote|work from home|wfh|anywhere|worldwide|distributed|telecommute|fully remote)\b",
    re.IGNORECASE,
)
HYBRID_RE = re.compile(
    r"\b(hybrid|partially remote|partial remote|flexible (?:work|location|office))\b",
    re.IGNORECASE,
)
ONSITE_RE = re.compile(
    r"\b(on[- ]?site|in[- ]?office|office[- ]?based|relocation required|must be located)\b",
    re.IGNORECASE,
)

FIT_MATRIX: dict[WorkPreference, dict[WorkMode, float]] = {
    "remote": {"remote": 1.0, "hybrid": 0.6, "on_site": 0.15, "unknown": 0.75},
    "hybrid": {"remote": 0.6, "hybrid": 1.0, "on_site": 0.5, "unknown": 0.7},
    "on_site": {"remote": 0.15, "hybrid": 0.5, "on_site": 1.0, "unknown": 0.4},
    "any": {"remote": 1.0, "hybrid": 1.0, "on_site": 1.0, "unknown": 1.0},
}

VALID_PREFERENCES = frozenset(FIT_MATRIX)


def normalize_work_preference(value: str | None) -> WorkPreference:
    if not value:
        return "any"

    cleaned = value.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "onsite": "on_site",
        "on_site": "on_site",
        "in_office": "on_site",
        "office": "on_site",
        "wfh": "remote",
        "work_from_home": "remote",
        "flexible": "hybrid",
        "no_preference": "any",
        "open": "any",
    }
    cleaned = aliases.get(cleaned, cleaned)
    if cleaned in VALID_PREFERENCES:
        return cleaned  # type: ignore[return-value]
    return "any"


def infer_work_preference(*, location: str = "", text: str = "") -> WorkPreference:
    blob = f"{location} {text}".lower()
    if re.search(r"\b(prefer|seeking|looking for|open to)\s+.{0,20}\bremote\b", blob):
        return "remote"
    if re.search(r"\b(prefer|seeking|looking for|open to)\s+.{0,20}\bhybrid\b", blob):
        return "hybrid"
    if re.search(r"\b(prefer|seeking|looking for|open to)\s+.{0,20}\b(on[- ]?site|in[- ]?office)\b", blob):
        return "on_site"
    if "remote" in location.lower() or location.lower() in {"wfh", "work from home"}:
        return "remote"
    if "hybrid" in location.lower():
        return "hybrid"
    return "any"


def classify_job_work_mode(job: JobPost) -> WorkMode:
    blob = " ".join(
        [
            job.title,
            job.location,
            job.description,
            " ".join(job.tags),
            job.category,
        ]
    )

    if HYBRID_RE.search(blob):
        return "hybrid"
    if ONSITE_RE.search(blob):
        return "on_site"
    if REMOTE_RE.search(blob):
        return "remote"
    if job.source in REMOTE_SOURCE_DEFAULTS:
        return "remote"
    if job.source in INTERNSHIP_SOURCE_DEFAULTS:
        if REMOTE_RE.search(blob):
            return "remote"
        return "on_site"
    if job.source in ONSITE_SOURCE_DEFAULTS:
        if REMOTE_RE.search(blob):
            return "remote"
        return "on_site"
    if job.location.strip():
        location = job.location.lower()
        if any(token in location for token in ("remote", "anywhere", "worldwide", "wfh")):
            return "remote"
        return "on_site"
    return "unknown"


def work_mode_fit(preference: WorkPreference, job_mode: WorkMode) -> float:
    return FIT_MATRIX.get(preference, FIT_MATRIX["any"]).get(job_mode, 0.5)


def job_work_mode_weight(job: JobPost, preference: WorkPreference) -> float:
    return work_mode_fit(preference, classify_job_work_mode(job))


def preference_label(preference: WorkPreference) -> str:
    return {
        "remote": "remote",
        "hybrid": "hybrid",
        "on_site": "on-site",
        "any": "any work mode",
    }[preference]


def matching_job_share(jobs: list[JobPost], preference: WorkPreference) -> float:
    if not jobs or preference == "any":
        return 1.0
    matches = sum(1 for job in jobs if work_mode_fit(preference, classify_job_work_mode(job)) >= 0.5)
    return matches / len(jobs)
