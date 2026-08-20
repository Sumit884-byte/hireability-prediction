import json
import re
from functools import lru_cache

from hireability.config import ROOT_DIR

TIER_MULTIPLIERS = {1: 1.15, 2: 1.08, 3: 1.04}
EXPERIENCE_BRACKETS = (
    (0, 1, 0.88),
    (1, 3, 0.94),
    (3, 5, 0.98),
    (5, 8, 1.00),
    (8, 12, 1.06),
    (12, 20, 1.10),
    (20, 100, 1.08),
)


@lru_cache(maxsize=1)
def _company_lookup() -> dict[str, tuple[int, str]]:
    path = ROOT_DIR / "data" / "company_tiers.json"
    with path.open(encoding="utf-8") as handle:
        tiers = json.load(handle)

    lookup: dict[str, tuple[int, str]] = {}
    for tier_key, companies in tiers.items():
        tier_num = int(tier_key.replace("tier", ""))
        for company in companies:
            lookup[company.lower()] = (tier_num, company)
    return lookup


def _normalize_company(name: str) -> str:
    cleaned = re.sub(r"\s+", " ", name.strip().lower())
    cleaned = re.sub(r"[^a-z0-9&+.\- ]", "", cleaned)
    return cleaned


def lookup_employer(company: str) -> tuple[int, str] | None:
    if not company:
        return None
    lookup = _company_lookup()
    normalized = _normalize_company(company)
    if normalized in lookup:
        return lookup[normalized]

    for alias, value in lookup.items():
        if alias in normalized or normalized in alias:
            return value
    return None


def best_employer_tier(companies: list[str]) -> tuple[str, int, float]:
    best_name = ""
    best_tier = 0
    best_multiplier = 1.0

    for company in companies:
        match = lookup_employer(company)
        if not match:
            continue
        tier, canonical = match
        multiplier = TIER_MULTIPLIERS[tier]
        if multiplier > best_multiplier:
            best_tier = tier
            best_name = canonical.title()
            best_multiplier = multiplier

    return best_name, best_tier, best_multiplier


def known_company_aliases() -> dict[str, str]:
    return {alias: canonical for alias, (_, canonical) in _company_lookup().items()}


def experience_multiplier(years: float, has_work_experience: bool = True) -> float:
    if not has_work_experience:
        return 1.0

    years = max(years, 0.0)
    for low, high, multiplier in EXPERIENCE_BRACKETS:
        if low <= years < high:
            return multiplier
    return 1.0


def readiness_multiplier(
    *,
    is_student: bool,
    has_degree: bool,
    has_work_experience: bool,
) -> float:
    """
    Learning agility: students have less time to pivot skills; graduates
    with work history can upskill faster and carry credential signal.
    """
    if is_student:
        multiplier = 0.90
        if has_degree:
            multiplier += 0.03
        if has_work_experience:
            multiplier += 0.04
        return round(min(multiplier, 0.96), 2)

    multiplier = 1.0
    if has_degree:
        multiplier += 0.04
    if has_work_experience:
        multiplier += 0.02
    return round(min(multiplier, 1.06), 2)


def readiness_label(
    *,
    is_student: bool,
    has_degree: bool,
    has_work_experience: bool,
) -> str:
    if is_student:
        bits = ["student"]
        if has_degree:
            bits.append("prior degree")
        if has_work_experience:
            bits.append("with work experience")
        return " ".join(bits)

    if has_degree and has_work_experience:
        return "degree + employed"
    if has_degree:
        return "degree holder"
    if has_work_experience:
        return "working professional"
    return "no formal credential"


def experience_label(years: float, has_work_experience: bool = True) -> str:
    if not has_work_experience:
        return "project-based (no work history)"

    if years < 1:
        return "early career"
    if years < 3:
        return "junior"
    if years < 6:
        return "mid-level"
    if years < 12:
        return "senior"
    return "staff+"
