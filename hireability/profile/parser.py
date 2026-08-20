from dataclasses import dataclass, field
from pathlib import Path

import yaml

from hireability.jobs.work_mode import infer_work_preference, normalize_work_preference
from hireability.normalizer.skills import SkillNormalizer
from hireability.profile.education import (
    parse_degree_field,
    parse_degree_level,
    parse_education_flags,
)


@dataclass
class UserProfile:
    name: str
    role: str
    skills: dict[str, float] = field(default_factory=dict)
    location: str = ""
    work_preference: str = "any"
    is_student: bool = False
    has_degree: bool = False
    degree_level: str = "none"
    degree_field: str = "general"
    experience_years: float = 0.0
    has_work_experience: bool = False
    current_company: str = ""
    employers: list[str] = field(default_factory=list)


def _skills_from_mapping(raw: dict, normalizer: SkillNormalizer) -> dict[str, float]:
    skills: dict[str, float] = {}
    for item in raw.get("skills", []):
        if isinstance(item, str):
            canonical = normalizer.normalize_token(item)
            if canonical:
                skills[canonical] = max(skills.get(canonical, 0.0), 1.0)
        elif isinstance(item, dict):
            label = item.get("name") or item.get("skill")
            weight = float(item.get("weight", 1.0))
            canonical = normalizer.normalize_token(str(label))
            if canonical:
                skills[canonical] = max(skills.get(canonical, 0.0), weight)

    resume_text = raw.get("resume_text", "")
    if resume_text:
        extracted = normalizer.extract_from_text(resume_text)
        for skill, count in extracted.items():
            skills[skill] = max(skills.get(skill, 0.0), min(float(count), 3.0))

    return skills


def load_profile_from_yaml(path: Path, normalizer: SkillNormalizer | None = None) -> UserProfile:
    normalizer = normalizer or SkillNormalizer()
    with path.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    skills = _skills_from_mapping(raw, normalizer)
    if not skills:
        raise ValueError("Profile must include at least one skill via skills or resume_text.")

    employers = [str(item).strip() for item in raw.get("employers", []) if str(item).strip()]
    current_company = str(raw.get("current_company", "")).strip()
    if current_company and current_company not in employers:
        employers.insert(0, current_company)

    experience_years = float(raw.get("experience_years", 0.0))
    if "has_work_experience" in raw:
        has_work_experience = bool(raw["has_work_experience"])
    else:
        has_work_experience = experience_years > 0 or bool(current_company or employers)

    location = str(raw.get("location", "")).strip()
    explicit_pref = raw.get("work_preference") or raw.get("job_preference")
    if explicit_pref:
        work_preference = normalize_work_preference(str(explicit_pref))
    else:
        work_preference = infer_work_preference(
            location=location,
            text=str(raw.get("resume_text", "")),
        )

    role = str(raw.get("role", "")).strip()
    is_student, has_degree = parse_education_flags(
        raw,
        full_text=str(raw.get("resume_text", "")),
        has_work_experience=has_work_experience,
        role=role,
    )
    degree_level = parse_degree_level(
        raw,
        full_text=str(raw.get("resume_text", "")),
        is_student=is_student,
        has_degree=has_degree,
    )
    degree_field = parse_degree_field(
        raw,
        full_text=str(raw.get("resume_text", "")),
        role=role,
    )

    return UserProfile(
        name=raw.get("name", "Candidate"),
        role=role,
        skills=skills,
        location=location,
        work_preference=work_preference,
        is_student=is_student,
        has_degree=has_degree,
        degree_level=degree_level,
        degree_field=degree_field,
        experience_years=experience_years,
        has_work_experience=has_work_experience,
        current_company=current_company,
        employers=employers,
    )


def load_profile(path: Path, normalizer: SkillNormalizer | None = None) -> UserProfile:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from hireability.profile.pdf import load_profile_from_pdf

        return load_profile_from_pdf(path, normalizer=normalizer)
    if suffix in {".yaml", ".yml"}:
        return load_profile_from_yaml(path, normalizer=normalizer)

    raise ValueError(
        f"Unsupported profile format '{suffix}'. Use a .pdf, .yaml, or .yml file."
    )
