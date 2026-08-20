"""Estimate probable salary range from profile signals and scraped market data."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache

from hireability.config import ROOT_DIR
from hireability.jobs.degree_field import normalize_degree_field
from hireability.models import JobPost
from hireability.normalizer.skills import SkillNormalizer
from hireability.profile.parser import UserProfile
from hireability.scoring.pedigree import best_employer_tier, experience_label


@dataclass(frozen=True)
class SalaryEstimate:
    currency: str
    period: str
    low: int
    high: int
    midpoint: int
    confidence: str
    basis: str
    comparable_jobs: int
    market_label: str
    role_family: str
    seniority: str


def _detect_market(location: str, work_preference: str) -> str:
    blob = (location or "").lower()
    if any(token in blob for token in ("india", "bangalore", "bengaluru", "mumbai", "delhi", "hyderabad", "pune", "chennai", "gurgaon", "noida")):
        return "india"
    if any(token in blob for token in ("united states", "usa", "u.s.", "new york", "san francisco", "seattle", "austin", "california")):
        return "us"
    if work_preference == "remote":
        return "remote_global"
    return "remote_global"


def _role_family(profile: UserProfile) -> str:
    field = normalize_degree_field(profile.degree_field)  # type: ignore[arg-type]
    role_blob = f"{profile.role} {' '.join(profile.skills)}".lower()
    field_map = {
        "ai": "ai",
        "data_science": "data_science",
        "computer_science": "software_engineer",
        "software_engineering": "software_engineer",
        "business": "business",
        "design": "design",
    }
    if field in field_map:
        return field_map[field]
    if re.search(r"\b(machine learning|ml engineer|ai engineer|nlp|computer vision)\b", role_blob):
        return "ai"
    if re.search(r"\b(data scien|analytics|bi engineer)\b", role_blob):
        return "data_science"
    if re.search(r"\b(designer|ux|ui|product design)\b", role_blob):
        return "design"
    if re.search(r"\b(product manager|marketing|sales|mba|consultant)\b", role_blob):
        return "business"
    return "software_engineer"


def _seniority_key(profile: UserProfile) -> str:
    if profile.is_student:
        return "entry"
    label = experience_label(profile.experience_years, profile.has_work_experience)
    mapping = {
        "project-based (no work history)": "entry",
        "early career": "entry",
        "junior": "junior",
        "mid-level": "mid",
        "senior": "senior",
        "staff+": "staff",
    }
    return mapping.get(label, "mid")


@lru_cache(maxsize=1)
def _benchmarks() -> dict:
    path = ROOT_DIR / "data" / "salary_benchmarks.json"
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _benchmark_range(
    *,
    market: str,
    role_family: str,
    seniority: str,
    is_student: bool,
) -> tuple[str, str, float, float]:
    data = _benchmarks()["markets"]
    if is_student and market == "india":
        stipend = data["india"].get("stipend_monthly", {}).get(seniority, [0, 15000])
        return "INR", "month", float(stipend[0]), float(stipend[1])

    market_data = data.get(market) or data["remote_global"]
    roles = market_data["roles"]
    role_key = "intern" if is_student else role_family
    if role_key not in roles:
        role_key = "software_engineer"
    role_brackets = roles[role_key]
    bracket = (
        role_brackets.get(seniority)
        or role_brackets.get("mid")
        or role_brackets.get("junior")
        or role_brackets.get("entry")
        or [70_000, 110_000]
    )
    return market_data["currency"], market_data["period"], float(bracket[0]), float(bracket[1])


def _degree_multiplier(degree_level: str) -> float:
    return {
        "doctorate": 1.12,
        "master": 1.08,
        "bachelor": 1.04,
        "associate": 1.02,
        "none": 1.0,
    }.get(degree_level, 1.0)


def _job_matches_profile(job: JobPost, profile: UserProfile, normalizer: SkillNormalizer) -> bool:
    blob = f"{job.title} {job.description} {' '.join(job.tags)}".lower()
    hits = 0
    for skill in profile.skills:
        aliases = normalizer.aliases_for(skill)
        if any(alias.lower() in blob for alias in aliases):
            hits += 1
    if hits >= 1:
        return True
    role_tokens = [token for token in re.split(r"[^a-z0-9+]+", profile.role.lower()) if len(token) > 2]
    return any(token in blob for token in role_tokens[:4])


def _normalize_to_annual(amount: float, period: str) -> float:
    if period == "year":
        return amount
    if period == "month":
        return amount * 12
    if period == "week":
        return amount * 52
    if period == "hour":
        return amount * 40 * 52
    return amount


def _market_salary_pool(
    jobs: list[JobPost],
    profile: UserProfile,
    normalizer: SkillNormalizer,
    *,
    target_currency: str,
) -> list[tuple[float, float]]:
    values: list[tuple[float, float]] = []
    for job in jobs:
        if job.salary_min is None or job.salary_max is None:
            continue
        if job.salary_max <= 0 and job.salary_min <= 0:
            continue
        if not _job_matches_profile(job, profile, normalizer):
            continue
        currency = (job.salary_currency or target_currency).upper()
        if currency != target_currency:
            continue
        lo = _normalize_to_annual(job.salary_min, job.salary_period or "year")
        hi = _normalize_to_annual(job.salary_max, job.salary_period or "year")
        if hi > lo and hi < 50_000_000:
            values.append((lo, hi))
    return values


def estimate_salary(
    profile: UserProfile,
    jobs: list[JobPost],
    normalizer: SkillNormalizer | None = None,
) -> SalaryEstimate:
    normalizer = normalizer or SkillNormalizer()
    market = _detect_market(profile.location, profile.work_preference)
    role_family = _role_family(profile)
    seniority = _seniority_key(profile)
    currency, period, bench_lo, bench_hi = _benchmark_range(
        market=market,
        role_family=role_family,
        seniority=seniority,
        is_student=profile.is_student,
    )

    _, _, employer_mult = best_employer_tier(
        [profile.current_company, *profile.employers] if profile.current_company else profile.employers
    )
    degree_mult = _degree_multiplier(profile.degree_level)
    exp_mult = 1.0 + min(profile.experience_years, 12) * 0.02
    profile_mult = employer_mult * degree_mult * exp_mult

    bench_lo *= profile_mult
    bench_hi *= profile_mult

    market_values = _market_salary_pool(jobs, profile, normalizer, target_currency=currency)
    if profile.is_student and market == "india":
        market_values = [
            (lo, hi)
            for lo, hi in market_values
            if hi <= 100_000
        ]

    if len(market_values) >= 5:
        lows = sorted(lo for lo, _ in market_values)
        highs = sorted(hi for _, hi in market_values)
        mkt_lo = lows[len(lows) // 4]
        mkt_hi = highs[(3 * len(highs)) // 4]
        low = 0.4 * bench_lo + 0.6 * mkt_lo
        high = 0.4 * bench_hi + 0.6 * mkt_hi
        confidence = "high" if len(market_values) >= 12 else "medium"
        basis = "blended market + benchmarks"
    elif market_values:
        mkt_lo = min(lo for lo, _ in market_values)
        mkt_hi = max(hi for _, hi in market_values)
        low = 0.55 * bench_lo + 0.45 * mkt_lo
        high = 0.55 * bench_hi + 0.45 * mkt_hi
        confidence = "medium"
        basis = "limited market data + benchmarks"
    else:
        low, high = bench_lo, bench_hi
        confidence = "low"
        basis = "role/experience benchmarks"

    low_i = int(round(low / 1000) * 1000)
    high_i = int(round(high / 1000) * 1000)
    if high_i <= low_i:
        high_i = low_i + max(1000, int(low_i * 0.15))

    market_labels = {
        "india": "India",
        "us": "United States",
        "remote_global": "global remote",
    }
    return SalaryEstimate(
        currency=currency,
        period=period,
        low=low_i,
        high=high_i,
        midpoint=int((low_i + high_i) / 2),
        confidence=confidence,
        basis=basis,
        comparable_jobs=len(market_values),
        market_label=market_labels.get(market, market),
        role_family=role_family.replace("_", " "),
        seniority=seniority,
    )


def format_salary_range(estimate: SalaryEstimate) -> str:
    if estimate.currency == "INR":
        if estimate.period == "month":
            return f"₹{estimate.low:,}–₹{estimate.high:,}/month"
        if estimate.high >= 100_000:
            low_l = estimate.low / 100_000
            high_l = estimate.high / 100_000
            return f"₹{low_l:.1f}–{high_l:.1f} LPA"
        return f"₹{estimate.low:,}–₹{estimate.high:,}/year"

    symbol = {"$": "$", "USD": "$", "EUR": "€", "GBP": "£"}.get(estimate.currency, estimate.currency + " ")
    if estimate.period == "year":
        return f"{symbol}{estimate.low:,}–{symbol}{estimate.high:,}/year"
    return f"{symbol}{estimate.low:,}–{symbol}{estimate.high:,}/{estimate.period}"
