"""30/90-day market feature engineering for supply-demand time-lag modeling."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

import pandas as pd

from hireability.market.daily import load_market_daily_frame
from hireability.market.supply import month_daily_layoff_rate
from hireability.config import (
    BASELINE_WINDOW_DAYS,
    CURRENT_WINDOW_DAYS,
    FORECAST_HORIZON_DAYS,
    HISTORY_DAYS,
    MAX_RELATIVE_RATIO,
    MIN_RELATIVE_RATIO,
    SUPPLY_EPSILON,
)
from hireability.jobs.degree_field import job_degree_field_weight
from hireability.jobs.degree_requirements import job_degree_weight
from hireability.jobs.recruitment import iter_recruitment_contributions
from hireability.jobs.work_mode import job_work_mode_weight
from hireability.models import JobPost, LayoffEvent, MarketSnapshot
from hireability.normalizer.skills import SkillNormalizer


def build_daily_macro_frame(
    jobs: list[JobPost],
    layoffs: list[LayoffEvent],
    *,
    end_date: date | None = None,
    history_days: int = HISTORY_DAYS,
    work_preference: str = "any",
    degree_level: str = "none",
    degree_field: str = "general",
    is_student: bool = False,
    has_degree: bool = False,
) -> pd.DataFrame:
    end_date = end_date or date.today()
    start_date = end_date - timedelta(days=history_days)

    persisted = load_market_daily_frame(
        end_date=end_date,
        history_days=history_days,
    )
    if not persisted.empty and len(persisted) >= history_days // 2:
        return persisted[["date", "layoffs", "job_postings"]].copy()

    daily_layoffs: dict[date, float] = defaultdict(float)
    for event in layoffs:
        for event_date, amount in month_daily_layoff_rate(event):
            if start_date <= event_date <= end_date:
                daily_layoffs[event_date] += amount

    daily_jobs: dict[date, float] = defaultdict(float)
    for job in jobs:
        job_weight = (
            job_work_mode_weight(job, work_preference)
            * job_degree_weight(
                job,
                degree_level=degree_level,
                is_student=is_student,
                has_degree=has_degree,
            )
            * job_degree_field_weight(
                job,
                degree_field=degree_field,
                degree_level=degree_level,
            )
        )
        for open_date, share in iter_recruitment_contributions(
            job,
            job_weight,
            start_date=start_date,
            end_date=end_date,
        ):
            daily_jobs[open_date] += share

    rows = []
    cursor = start_date
    while cursor <= end_date:
        rows.append(
            {
                "date": cursor,
                "layoffs": daily_layoffs.get(cursor, 0.0),
                "job_postings": daily_jobs.get(cursor, 0.0),
            }
        )
        cursor += timedelta(days=1)

    return pd.DataFrame(rows)


def engineer_market_features(
    df: pd.DataFrame,
    *,
    current_window: int = CURRENT_WINDOW_DAYS,
    baseline_window: int = BASELINE_WINDOW_DAYS,
    forecast_horizon: int = FORECAST_HORIZON_DAYS,
) -> pd.DataFrame:
    """
    Apply the 30/90 rule:
    - 30-day rolling sums capture the current state
    - 90-day rolling means (shifted) provide the baseline normalizer
    - forward-shifted saturation supports supervised training at T+30
    """
    if df.empty:
        return df

    frame = df.sort_values("date").reset_index(drop=True).copy()

    frame["supply_30d"] = frame["layoffs"].rolling(
        window=current_window, min_periods=1
    ).sum()
    frame["demand_30d"] = frame["job_postings"].rolling(
        window=current_window, min_periods=1
    ).sum()

    # Baseline uses only prior context: 90-day mean of daily rates ending 30 days ago.
    shifted_layoffs = frame["layoffs"].shift(current_window)
    shifted_jobs = frame["job_postings"].shift(current_window)
    frame["supply_baseline_90d"] = shifted_layoffs.rolling(
        window=baseline_window, min_periods=1
    ).mean()
    frame["demand_baseline_90d"] = shifted_jobs.rolling(
        window=baseline_window, min_periods=1
    ).mean()

    expected_supply_30d = frame["supply_baseline_90d"] * current_window
    expected_demand_30d = frame["demand_baseline_90d"] * current_window

    # Sparse job history produces near-zero baselines after ingest. Assume the
    # current window is 2× the unknown baseline instead of dividing by ~0.
    expected_supply_30d = expected_supply_30d.where(
        expected_supply_30d >= SUPPLY_EPSILON,
        frame["supply_30d"] / 2.0,
    )
    expected_demand_30d = expected_demand_30d.where(
        expected_demand_30d >= SUPPLY_EPSILON,
        frame["demand_30d"] / 2.0,
    )

    frame["relative_supply_shock"] = (
        frame["supply_30d"] / (expected_supply_30d + SUPPLY_EPSILON)
    ).clip(MIN_RELATIVE_RATIO, MAX_RELATIVE_RATIO)
    frame["relative_demand_strength"] = (
        frame["demand_30d"] / (expected_demand_30d + SUPPLY_EPSILON)
    ).clip(MIN_RELATIVE_RATIO, MAX_RELATIVE_RATIO)
    frame["saturation_ratio"] = frame["supply_30d"] / (frame["demand_30d"] + SUPPLY_EPSILON)

    frame["target_future_saturation"] = frame["saturation_ratio"].shift(-forecast_horizon)

    return frame


def latest_market_snapshot(
    jobs: list[JobPost],
    layoffs: list[LayoffEvent],
    *,
    as_of: date | None = None,
    work_preference: str = "any",
    degree_level: str = "none",
    degree_field: str = "general",
    is_student: bool = False,
    has_degree: bool = False,
) -> MarketSnapshot:
    frame = build_daily_macro_frame(
        jobs,
        layoffs,
        end_date=as_of,
        work_preference=work_preference,
        degree_level=degree_level,
        degree_field=degree_field,
        is_student=is_student,
        has_degree=has_degree,
    )
    features = engineer_market_features(frame)
    if features.empty:
        today = as_of or date.today()
        return MarketSnapshot(
            as_of=today,
            supply_30d=0.0,
            demand_30d=0.0,
            supply_baseline_90d=0.0,
            demand_baseline_90d=0.0,
            relative_supply_shock=1.0,
            relative_demand_strength=1.0,
            saturation_ratio=1.0,
        )

    row = features.iloc[-1]
    future = row.get("target_future_saturation")
    return MarketSnapshot(
        as_of=row["date"].date() if hasattr(row["date"], "date") else row["date"],
        supply_30d=float(row["supply_30d"]),
        demand_30d=float(row["demand_30d"]),
        supply_baseline_90d=float(row["supply_baseline_90d"]),
        demand_baseline_90d=float(row["demand_baseline_90d"]),
        relative_supply_shock=float(row["relative_supply_shock"]),
        relative_demand_strength=float(row["relative_demand_strength"]),
        saturation_ratio=float(row["saturation_ratio"]),
        future_saturation_t30=float(future) if pd.notna(future) else None,
    )


def _skill_job_weight(
    job: JobPost,
    skill: str,
    normalizer: SkillNormalizer,
    *,
    work_preference: str = "any",
    degree_level: str = "none",
    degree_field: str = "general",
    is_student: bool = False,
    has_degree: bool = False,
) -> float:
    tags = normalizer.extract_from_tags(job.tags)
    text = normalizer.extract_from_text(f"{job.title} {job.description}")
    base = float(tags.get(skill, 0) + text.get(skill, 0))
    if base <= 0:
        return 0.0
    return (
        base
        * job_work_mode_weight(job, work_preference)
        * job_degree_weight(
            job,
            degree_level=degree_level,
            is_student=is_student,
            has_degree=has_degree,
        )
        * job_degree_field_weight(
            job,
            degree_field=degree_field,
            degree_level=degree_level,
        )
    )


def _skill_supply_amount(
    event: LayoffEvent, skill: str, normalizer: SkillNormalizer
) -> float:
    if skill not in normalizer.skills_for_industry(event.industry):
        return 0.0
    skills = normalizer.skills_for_industry(event.industry)
    return event.headcount / max(len(skills), 1)


def build_skill_daily_frame(
    skill: str,
    jobs: list[JobPost],
    layoffs: list[LayoffEvent],
    normalizer: SkillNormalizer,
    *,
    end_date: date | None = None,
    history_days: int = HISTORY_DAYS,
    work_preference: str = "any",
    degree_level: str = "none",
    degree_field: str = "general",
    is_student: bool = False,
    has_degree: bool = False,
) -> pd.DataFrame:
    end_date = end_date or date.today()
    start_date = end_date - timedelta(days=history_days)

    daily_layoffs: dict[date, float] = defaultdict(float)
    for event in layoffs:
        for event_date, amount in month_daily_layoff_rate(event):
            if start_date <= event_date <= end_date:
                daily_layoffs[event_date] += _skill_supply_amount(event, skill, normalizer) * (
                    amount / max(event.headcount, 1)
                )

    daily_jobs: dict[date, float] = defaultdict(float)
    for job in jobs:
        weight = _skill_job_weight(
            job,
            skill,
            normalizer,
            work_preference=work_preference,
            degree_level=degree_level,
            degree_field=degree_field,
            is_student=is_student,
            has_degree=has_degree,
        )
        if weight <= 0:
            continue
        for open_date, share in iter_recruitment_contributions(
            job,
            weight,
            start_date=start_date,
            end_date=end_date,
        ):
            daily_jobs[open_date] += share

    rows = []
    cursor = start_date
    while cursor <= end_date:
        rows.append(
            {
                "date": cursor,
                "layoffs": daily_layoffs.get(cursor, 0.0),
                "job_postings": daily_jobs.get(cursor, 0.0),
            }
        )
        cursor += timedelta(days=1)

    return pd.DataFrame(rows)


def skill_relative_ratio(
    skill: str,
    jobs: list[JobPost],
    layoffs: list[LayoffEvent],
    normalizer: SkillNormalizer,
    *,
    as_of: date | None = None,
    work_preference: str = "any",
    degree_level: str = "none",
    degree_field: str = "general",
    is_student: bool = False,
    has_degree: bool = False,
) -> tuple[float, float, float]:
    """Return (demand_30d, supply_30d, paradox-adjusted ratio) for one skill."""
    frame = build_skill_daily_frame(
        skill,
        jobs,
        layoffs,
        normalizer,
        end_date=as_of,
        work_preference=work_preference,
        degree_level=degree_level,
        degree_field=degree_field,
        is_student=is_student,
        has_degree=has_degree,
    )
    features = engineer_market_features(frame)
    if features.empty:
        return 0.0, 0.0, 1.0

    row = features.iloc[-1]
    demand_30d = float(row["demand_30d"])
    supply_30d = float(row["supply_30d"])
    relative_demand = float(row["relative_demand_strength"])
    relative_supply = float(row["relative_supply_shock"])
    ratio = relative_demand / (relative_supply + SUPPLY_EPSILON)
    return demand_30d, supply_30d, ratio


def build_training_matrix(
    jobs: list[JobPost],
    layoffs: list[LayoffEvent],
    *,
    history_days: int = HISTORY_DAYS,
) -> pd.DataFrame:
    """Exportable feature matrix with forward-shifted saturation target."""
    frame = build_daily_macro_frame(jobs, layoffs, history_days=history_days)
    features = engineer_market_features(frame)
    return features.dropna().reset_index(drop=True)
