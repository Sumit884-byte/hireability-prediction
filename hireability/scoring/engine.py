import math
from datetime import date, datetime, timedelta

from hireability.config import CURRENT_WINDOW_DAYS
from hireability.jobs.degree_field import field_label, matching_field_share
from hireability.jobs.degree_requirements import (
    degree_fit_note,
    degree_level_label,
    matching_degree_share,
)
from hireability.jobs.hiring_lag import cached_hiring_lag_model, lag_summary
from hireability.jobs.recruitment import recruitment_stats
from hireability.jobs.work_mode import matching_job_share, preference_label
from hireability.models import HireabilityResult, JobPost, LayoffEvent, MarketSnapshot, SkillSignal
from hireability.normalizer.skills import SkillNormalizer
from hireability.profile.parser import UserProfile
from hireability.scoring.pedigree import (
    best_employer_tier,
    experience_label,
    experience_multiplier,
    readiness_label,
    readiness_multiplier,
)
from hireability.scoring.timeseries import latest_market_snapshot, skill_relative_ratio
from hireability.scoring.salary import estimate_salary, format_salary_range
from hireability.scoring.verdict import VERDICT_LABELS, market_verdict


def _cap_ratio(ratio: float, cap: float = 4.0) -> float:
    return min(ratio, cap)


def _ratio_to_score(ratio: float) -> float:
    capped = _cap_ratio(ratio)
    return 100.0 / (1.0 + math.exp(-1.2 * (capped - 1.0)))


def _trend_label(current_ratio: float, prior_ratio: float) -> str:
    delta = current_ratio - prior_ratio
    if delta > 0.15:
        return "improving"
    if delta < -0.15:
        return "declining"
    return "stable"


def _prior_period_ratio(
    skill: str,
    jobs: list[JobPost],
    layoffs: list[LayoffEvent],
    normalizer: SkillNormalizer,
    as_of: date,
    *,
    work_preference: str,
    degree_level: str,
    degree_field: str,
    is_student: bool,
    has_degree: bool,
) -> float:
    _, _, ratio = skill_relative_ratio(
        skill,
        jobs,
        layoffs,
        normalizer,
        as_of=as_of,
        work_preference=work_preference,
        degree_level=degree_level,
        degree_field=degree_field,
        is_student=is_student,
        has_degree=has_degree,
    )
    return _cap_ratio(ratio)


def compute_hireability(
    profile: UserProfile,
    jobs: list[JobPost],
    layoffs: list[LayoffEvent],
    normalizer: SkillNormalizer | None = None,
    window_days: int = CURRENT_WINDOW_DAYS,
) -> HireabilityResult:
    normalizer = normalizer or SkillNormalizer()
    today = datetime.utcnow().date()
    prior_date = today - timedelta(days=window_days)
    work_preference = profile.work_preference or "any"
    degree_level = profile.degree_level or "none"
    degree_field = profile.degree_field or "general"
    job_match_share = matching_job_share(jobs, work_preference)
    degree_match_share = matching_degree_share(
        jobs,
        degree_level=degree_level,
        is_student=profile.is_student,
        has_degree=profile.has_degree,
    )
    field_match_share = matching_field_share(
        jobs,
        degree_field=degree_field,
        degree_level=degree_level,
    )

    market = latest_market_snapshot(
        jobs,
        layoffs,
        as_of=today,
        work_preference=work_preference,
        degree_level=degree_level,
        degree_field=degree_field,
        is_student=profile.is_student,
        has_degree=profile.has_degree,
    )

    skill_signals: list[SkillSignal] = []
    weighted_ratios: list[float] = []
    prior_weighted_ratios: list[float] = []
    weights: list[float] = []

    for skill, profile_weight in profile.skills.items():
        demand_30d, supply_30d, raw_ratio = skill_relative_ratio(
            skill,
            jobs,
            layoffs,
            normalizer,
            as_of=today,
            work_preference=work_preference,
            degree_level=degree_level,
            degree_field=degree_field,
            is_student=profile.is_student,
            has_degree=profile.has_degree,
        )
        ratio = _cap_ratio(raw_ratio)
        prior_ratio = _prior_period_ratio(
            skill,
            jobs,
            layoffs,
            normalizer,
            prior_date,
            work_preference=work_preference,
            degree_level=degree_level,
            degree_field=degree_field,
            is_student=profile.is_student,
            has_degree=profile.has_degree,
        )

        skill_signals.append(
            SkillSignal(
                skill=skill,
                demand_score=round(demand_30d, 3),
                supply_score=round(supply_30d, 3),
                ratio=round(raw_ratio, 3),
                profile_weight=profile_weight,
            )
        )
        weighted_ratios.append(ratio * profile_weight)
        prior_weighted_ratios.append(prior_ratio * profile_weight)
        weights.append(profile_weight)

    total_weight = sum(weights) or 1.0
    aggregate_ratio = sum(weighted_ratios) / total_weight
    prior_aggregate_ratio = sum(prior_weighted_ratios) / total_weight
    market_score = round(_ratio_to_score(aggregate_ratio), 1)
    trend = _trend_label(aggregate_ratio, prior_aggregate_ratio)

    skill_signals.sort(key=lambda item: item.ratio * item.profile_weight, reverse=True)

    exp_mult = experience_multiplier(
        profile.experience_years,
        has_work_experience=profile.has_work_experience,
    )
    exp_label = experience_label(
        profile.experience_years,
        has_work_experience=profile.has_work_experience,
    )

    employer_candidates = []
    if profile.current_company:
        employer_candidates.append(profile.current_company)
    employer_candidates.extend(profile.employers)
    employer_name, employer_tier, employer_mult = best_employer_tier(employer_candidates)
    readiness_mult = readiness_multiplier(
        is_student=profile.is_student,
        has_degree=profile.has_degree,
        has_work_experience=profile.has_work_experience,
    )
    readiness_lbl = readiness_label(
        is_student=profile.is_student,
        has_degree=profile.has_degree,
        has_work_experience=profile.has_work_experience,
    )

    score = round(
        min(100.0, market_score * exp_mult * employer_mult * readiness_mult),
        1,
    )

    lag_model = cached_hiring_lag_model()
    recruiting = recruitment_stats(jobs, as_of=today, model=lag_model)
    verdict, verdict_detail = market_verdict(market_score, market.saturation_ratio)
    outlook = VERDICT_LABELS[verdict]
    recruit_note = (
        f" Active recruitment: {recruiting['active_roles']} roles "
        f"(avg {recruiting['avg_duration']:.0f}d window from {lag_summary(lag_model)}, "
        f"{recruiting['avg_progress']:.0%} through cycle)."
    )

    pedigree_bits = []
    if profile.has_work_experience and profile.experience_years > 0:
        pedigree_bits.append(f"{profile.experience_years:g} yrs ({exp_label})")
    elif not profile.has_work_experience:
        pedigree_bits.append(exp_label)
    if employer_name:
        pedigree_bits.append(f"{employer_name} (tier {employer_tier})")
    pedigree_bits.append(f"readiness: {readiness_lbl}")
    pedigree_note = f" Profile signals: {', '.join(pedigree_bits)}." if pedigree_bits else ""

    work_note = (
        f" Work preference: {preference_label(work_preference)}"
        f" ({job_match_share:.0%} of jobs match)."
        f" Degree fit: {degree_fit_note(degree_level=degree_level, is_student=profile.is_student, has_degree=profile.has_degree)}"
        f" ({degree_match_share:.0%} of jobs meet education bar)."
        f" Field: {field_label(degree_field)} ({field_match_share:.0%} of jobs match specialization)."
    )

    salary = estimate_salary(profile, jobs, normalizer)
    salary_label = format_salary_range(salary)
    salary_note = (
        f" Probable salary ({salary.market_label}, {salary.role_family}, {salary.seniority}):"
        f" {salary_label} ({salary.confidence} confidence, {salary.comparable_jobs} comparable postings)."
    )

    summary = (
        f"{profile.name}: {score}% hireability — market outlook {outlook} "
        f"({trend}). {verdict_detail}"
        f" Score uses 30-day state vs 90-day baseline."
        f" Market fit {market_score}% × experience {exp_mult:.2f} × "
        f"employer {employer_mult:.2f} × readiness {readiness_mult:.2f}."
        f" Supply shock {market.relative_supply_shock:.2f}×,"
        f" demand strength {market.relative_demand_strength:.2f}×."
        f"{salary_note}{work_note}{recruit_note}{pedigree_note}"
    )

    return HireabilityResult(
        score=score,
        market_score=market_score,
        trend=trend,
        window_days=window_days,
        skills=skill_signals,
        summary=summary,
        experience_years=profile.experience_years,
        experience_multiplier=exp_mult,
        experience_label=exp_label,
        employer_name=employer_name,
        employer_tier=employer_tier,
        employer_multiplier=employer_mult,
        readiness_multiplier=readiness_mult,
        readiness_label=readiness_lbl,
        is_student=profile.is_student,
        has_degree=profile.has_degree,
        degree_level=degree_level,
        degree_field=degree_field,
        work_preference=work_preference,
        matching_job_share=job_match_share,
        matching_degree_share=degree_match_share,
        matching_field_share=field_match_share,
        market_verdict=verdict,
        market_verdict_detail=verdict_detail,
        active_recruitment_roles=int(recruiting["active_roles"]),
        avg_recruitment_progress=recruiting["avg_progress"],
        avg_recruitment_duration=recruiting["avg_duration"],
        hiring_lag_note=lag_summary(lag_model),
        market=market,
        salary_low=salary.low,
        salary_high=salary.high,
        salary_currency=salary.currency,
        salary_period=salary.period,
        salary_range_label=salary_label,
        salary_confidence=salary.confidence,
        salary_basis=salary.basis,
        salary_comparable_jobs=salary.comparable_jobs,
    )
