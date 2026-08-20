"""Model active recruitment windows using empirical hiring lag when available."""

from __future__ import annotations

from datetime import date, timedelta

from hireability.config import RECRUITMENT_COMPETITION_RAMP
from hireability.jobs.hiring_lag import (
    HiringLagModel,
    cached_hiring_lag_model,
    observed_open_days,
    recruitment_duration_days,
    recruitment_start,
)
from hireability.models import JobPost


def _day_shape(day_offset: int, duration: int) -> float:
    if day_offset >= duration:
        return 0.0
    progress = day_offset / max(duration - 1, 1)
    return max(0.3, 1.0 - RECRUITMENT_COMPETITION_RAMP * progress)


def _normalizer(duration: int) -> float:
    return sum(_day_shape(day, duration) for day in range(duration)) or 1.0


def job_days_open(job: JobPost, as_of: date | None = None) -> int:
    as_of = as_of or date.today()
    return max(0, (as_of - recruitment_start(job)).days)


def recruitment_duration(
    job: JobPost,
    model: HiringLagModel | None = None,
) -> int:
    return recruitment_duration_days(job, model)


def is_still_recruiting(
    job: JobPost,
    as_of: date | None = None,
    *,
    model: HiringLagModel | None = None,
) -> bool:
    as_of = as_of or date.today()
    duration = recruitment_duration(job, model)
    return 0 <= job_days_open(job, as_of) < duration


def recruitment_progress(
    job: JobPost,
    as_of: date | None = None,
    *,
    model: HiringLagModel | None = None,
) -> float:
    as_of = as_of or date.today()
    duration = recruitment_duration(job, model)
    if duration <= 0:
        return 1.0
    return min(1.0, job_days_open(job, as_of) / duration)


def remaining_opportunity_weight(
    job: JobPost,
    as_of: date | None = None,
    *,
    model: HiringLagModel | None = None,
) -> float:
    as_of = as_of or date.today()
    if not is_still_recruiting(job, as_of, model=model):
        return 0.0
    duration = recruitment_duration(job, model)
    day_offset = job_days_open(job, as_of)
    return _day_shape(day_offset, duration) / _normalizer(duration)


def iter_recruitment_contributions(
    job: JobPost,
    weight: float,
    *,
    start_date: date,
    end_date: date,
    model: HiringLagModel | None = None,
):
    model = model or cached_hiring_lag_model()
    duration = recruitment_duration(job, model)
    scale = _normalizer(duration)
    window_start = recruitment_start(job)

    for day_offset in range(duration):
        open_date = window_start + timedelta(days=day_offset)
        if open_date < start_date or open_date > end_date:
            continue
        share = _day_shape(day_offset, duration) / scale
        yield open_date, weight * share


def recruitment_stats(
    jobs: list[JobPost],
    as_of: date | None = None,
    *,
    model: HiringLagModel | None = None,
) -> dict[str, float]:
    as_of = as_of or date.today()
    model = model or cached_hiring_lag_model()

    if not jobs:
        return {
            "active_roles": 0,
            "avg_days_open": 0.0,
            "avg_progress": 0.0,
            "avg_opportunity": 0.0,
            "avg_duration": 0.0,
            "empirical_roles": 0,
        }

    active = [job for job in jobs if is_still_recruiting(job, as_of, model=model)]
    days_open = [job_days_open(job, as_of) for job in active]
    progress = [recruitment_progress(job, as_of, model=model) for job in active]
    opportunity = [remaining_opportunity_weight(job, as_of, model=model) for job in active]
    durations = [recruitment_duration(job, model) for job in active]
    empirical = sum(
        1
        for job in active
        if job.sighting_days >= 2
        or model.for_source(job.source).data_driven
    )

    return {
        "active_roles": len(active),
        "avg_days_open": sum(days_open) / len(days_open) if days_open else 0.0,
        "avg_progress": sum(progress) / len(progress) if progress else 0.0,
        "avg_opportunity": sum(opportunity) / len(opportunity) if opportunity else 0.0,
        "avg_duration": sum(durations) / len(durations) if durations else 0.0,
        "empirical_roles": empirical,
    }
