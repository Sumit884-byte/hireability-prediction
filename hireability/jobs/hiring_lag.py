"""Empirical hiring lag from repeated daily job sightings."""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path

from hireability.config import DB_PATH, RECRUITMENT_DURATION_DAYS
from hireability.models import JobPost
from hireability.storage import _connect, init_db


@dataclass
class SourceLagProfile:
    median_days: float
    p75_days: float
    p90_days: float
    sample_size: int
    data_driven: bool = False


@dataclass
class HiringLagModel:
    global_profile: SourceLagProfile
    by_source: dict[str, SourceLagProfile] = field(default_factory=dict)

    def for_source(self, source: str) -> SourceLagProfile:
        return self.by_source.get(source, self.global_profile)


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return float(RECRUITMENT_DURATION_DAYS)
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * pct))))
    return ordered[index]


def _profile_from_values(values: list[float], *, min_samples: int = 5) -> SourceLagProfile:
    # True hiring lag needs jobs observed on 2+ distinct days (daily ingest sightings).
    usable = [value for value in values if value >= 2.0]
    if len(usable) < min_samples:
        fallback = float(RECRUITMENT_DURATION_DAYS)
        return SourceLagProfile(
            median_days=fallback,
            p75_days=fallback,
            p90_days=fallback,
            sample_size=len(usable),
            data_driven=False,
        )
    return SourceLagProfile(
        median_days=max(7.0, statistics.median(usable)),
        p75_days=max(10.0, _percentile(usable, 0.75)),
        p90_days=max(14.0, _percentile(usable, 0.90)),
        sample_size=len(usable),
        data_driven=True,
    )


def _open_days(first_seen: date, last_seen: date) -> float:
    return float((last_seen - first_seen).days + 1)


def load_hiring_lag_model(db_path: Path = DB_PATH) -> HiringLagModel:
    init_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                j.source,
                j.first_seen,
                j.last_seen,
                j.posted_date,
                COALESCE(s.sighting_days, 1) AS sighting_days
            FROM job_posts j
            LEFT JOIN (
                SELECT content_hash, COUNT(DISTINCT sighting_date) AS sighting_days
                FROM job_sightings
                GROUP BY content_hash
            ) s ON s.content_hash = j.content_hash
            WHERE j.first_seen IS NOT NULL AND j.last_seen IS NOT NULL
            """
        ).fetchall()

    global_values: list[float] = []
    by_source_values: dict[str, list[float]] = {}

    for row in rows:
        first = date.fromisoformat(row["first_seen"])
        last = date.fromisoformat(row["last_seen"])
        open_days = _open_days(first, last)
        if int(row["sighting_days"]) >= 2:
            open_days = max(open_days, float(row["sighting_days"]))

        global_values.append(open_days)
        source = row["source"] or "unknown"
        by_source_values.setdefault(source, []).append(open_days)

    by_source = {
        source: _profile_from_values(values)
        for source, values in by_source_values.items()
    }
    return HiringLagModel(
        global_profile=_profile_from_values(global_values),
        by_source=by_source,
    )


@lru_cache(maxsize=1)
def cached_hiring_lag_model(db_path: str = str(DB_PATH)) -> HiringLagModel:
    return load_hiring_lag_model(Path(db_path))


def recruitment_start(job: JobPost) -> date:
    return job.first_seen or job.posted_date


def observed_open_days(job: JobPost, as_of: date | None = None) -> int:
    as_of = as_of or date.today()
    start = recruitment_start(job)
    if job.last_seen:
        return max(1, (job.last_seen - start).days + 1)
    return max(1, (as_of - start).days + 1)


def recruitment_duration_days(job: JobPost, model: HiringLagModel | None = None) -> int:
    """
    Per-job recruitment window using empirical lag when available.

    Uses observed open span from sightings, capped by source p90 from true data.
    """
    model = model or cached_hiring_lag_model()
    profile = model.for_source(job.source)
    base = int(round(profile.p90_days))
    observed = observed_open_days(job)

    if job.sighting_days >= 2 or (job.first_seen and job.last_seen and job.first_seen != job.last_seen):
        return max(7, min(90, max(observed, int(round(profile.median_days)))))

    if profile.data_driven:
        return max(14, min(90, base))

    return RECRUITMENT_DURATION_DAYS


def lag_summary(model: HiringLagModel | None = None) -> str:
    model = model or cached_hiring_lag_model()
    g = model.global_profile
    if g.data_driven:
        return (
            f"empirical median {g.median_days:.0f}d "
            f"(p90 {g.p90_days:.0f}d, {g.sample_size} multi-day jobs)"
        )
    return (
        f"default {RECRUITMENT_DURATION_DAYS}d "
        f"({g.sample_size} multi-day jobs — run daily ingest for true lag)"
    )
