from dataclasses import dataclass, field
from datetime import date


@dataclass
class LayoffEvent:
    company: str
    event_date: date
    headcount: int
    industry: str = "Technology"
    country: str = ""
    source: str = ""


@dataclass
class JobPost:
    title: str
    company: str
    posted_date: date
    description: str
    tags: list[str] = field(default_factory=list)
    category: str = ""
    location: str = ""
    source: str = ""
    url: str = ""
    content_hash: str = ""
    first_seen: date | None = None
    last_seen: date | None = None
    sighting_days: int = 0
    title_original: str | None = None
    description_original: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str = ""
    salary_period: str = ""


@dataclass
class MarketSnapshot:
    as_of: date
    supply_30d: float
    demand_30d: float
    supply_baseline_90d: float
    demand_baseline_90d: float
    relative_supply_shock: float
    relative_demand_strength: float
    saturation_ratio: float
    future_saturation_t30: float | None = None


@dataclass
class SkillSignal:
    skill: str
    demand_score: float
    supply_score: float
    ratio: float
    profile_weight: float


@dataclass
class HireabilityResult:
    score: float
    market_score: float
    trend: str
    window_days: int
    skills: list[SkillSignal]
    summary: str
    experience_years: float = 0.0
    experience_multiplier: float = 1.0
    experience_label: str = ""
    employer_name: str = ""
    employer_tier: int = 0
    employer_multiplier: float = 1.0
    readiness_multiplier: float = 1.0
    readiness_label: str = ""
    is_student: bool = False
    has_degree: bool = False
    degree_level: str = "none"
    degree_field: str = "general"
    work_preference: str = "any"
    matching_job_share: float = 1.0
    matching_degree_share: float = 1.0
    matching_field_share: float = 1.0
    market_verdict: str = "bad"
    market_verdict_detail: str = ""
    active_recruitment_roles: int = 0
    avg_recruitment_progress: float = 0.0
    avg_recruitment_duration: float = 0.0
    hiring_lag_note: str = ""
    market: MarketSnapshot | None = None
    salary_low: int = 0
    salary_high: int = 0
    salary_currency: str = ""
    salary_period: str = ""
    salary_range_label: str = ""
    salary_confidence: str = ""
    salary_basis: str = ""
    salary_comparable_jobs: int = 0
