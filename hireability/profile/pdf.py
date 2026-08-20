import re
from datetime import date
from pathlib import Path

from dateutil import parser as date_parser
from pypdf import PdfReader

from hireability.jobs.work_mode import infer_work_preference
from hireability.normalizer.skills import SkillNormalizer
from hireability.profile.education import (
    infer_degree_level,
    infer_education_status,
    parse_degree_field,
)
from hireability.profile.parser import UserProfile
from hireability.scoring.pedigree import known_company_aliases

SECTION_BREAK_RE = re.compile(
    r"\n(?=(?:PROFESSIONAL SUMMARY|SUMMARY|TECHNICAL SKILLS|SKILLS|"
    r"EXPERIENCE|WORK EXPERIENCE|EMPLOYMENT|PROJECTS|EDUCATION|CERTIFICATIONS)\b)",
    re.IGNORECASE,
)
SKILLS_SECTION_RE = re.compile(r"^(?:technical )?skills\b", re.IGNORECASE)
EXPERIENCE_SECTION_RE = re.compile(r"^(?:work )?experience|employment\b", re.IGNORECASE)
EXPERIENCE_RE = re.compile(r"(\d+)\+?\s*(?:years?|yrs?)\s+(?:of\s+)?experience", re.IGNORECASE)
DATE_RANGE_RE = re.compile(
    r"(?:"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{4}"
    r"|"
    r"\d{4}"
    r")\s*[-–—to]+\s*"
    r"(?:"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{4}"
    r"|"
    r"\d{4}"
    r"|"
    r"present|current|now"
    r")",
    re.IGNORECASE,
)
COMPANY_LINE_RE = re.compile(
    r"^([A-Z][A-Za-z0-9&+.\- ]{1,60}?)"
    r"(?:\s*[-–—|]\s*(?:[A-Z][a-z].{2,40}|Remote|Internship))?$"
)


def extract_pdf_text(path: Path) -> str:
    reader = PdfReader(str(path))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(pages).strip()


def _clean_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if line and not re.fullmatch(r"[•\-\d]+", line):
            lines.append(line)
    return lines


def _parse_header(lines: list[str]) -> tuple[str, str, str]:
    if not lines:
        return "Candidate", "", ""

    name = lines[0].strip().title()
    role = ""
    location = ""

    if len(lines) > 1:
        header = lines[1]
        if "|" in header:
            parts = [part.strip() for part in header.split("|") if part.strip()]
            if parts:
                role = parts[0]
            if len(parts) > 1:
                location = parts[-1]
        else:
            role = header

    return name, role, location


def _split_sections(text: str) -> dict[str, str]:
    parts = SECTION_BREAK_RE.split(text)
    sections: dict[str, str] = {"body": text}
    for part in parts:
        lines = part.strip().splitlines()
        if not lines:
            continue
        heading = lines[0].strip()
        body = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""
        sections[heading.lower()] = body or part.strip()
    return sections


def _skills_from_section(section_text: str, normalizer: SkillNormalizer, weight: float) -> dict[str, float]:
    skills: dict[str, float] = {}
    for skill, count in normalizer.extract_from_text(section_text).items():
        skills[skill] = max(skills.get(skill, 0.0), min(float(count) * weight, 3.0))
    return skills


def _parse_range_years(start_text: str, end_text: str) -> float:
    today = date.today()
    start = date_parser.parse(start_text, default=date(today.year, 1, 1)).date()
    if end_text.lower() in {"present", "current", "now"}:
        end = today
    else:
        end = date_parser.parse(end_text, default=date(today.year, 12, 31)).date()
    days = max((end - start).days, 0)
    return days / 365.25


def _work_experience_text(sections: dict[str, str]) -> str:
    return "\n".join(
        body for heading, body in sections.items() if EXPERIENCE_SECTION_RE.match(heading)
    ).strip()


def _has_work_experience(sections: dict[str, str], employers: list[str]) -> bool:
    experience_text = _work_experience_text(sections)
    if not experience_text:
        return False
    if employers:
        return True
    if DATE_RANGE_RE.search(experience_text):
        return True
    return bool(
        re.search(
            r"\b(?:software engineer|developer|intern|analyst|manager|consultant)\b",
            experience_text,
            re.IGNORECASE,
        )
    )


def _parse_experience_years(text: str, sections: dict[str, str]) -> float:
    experience_text = _work_experience_text(sections)

    if experience_text:
        match = EXPERIENCE_RE.search(experience_text)
        if match:
            return float(match.group(1))

        total_years = 0.0
        for raw_range in DATE_RANGE_RE.findall(experience_text):
            parts = re.split(r"\s*[-–—to]+\s*", raw_range, maxsplit=1, flags=re.IGNORECASE)
            if len(parts) == 2:
                total_years += _parse_range_years(parts[0], parts[1])
        if total_years > 0:
            return round(total_years, 1)

    # Only trust an explicit "N years of experience" claim outside work history.
    match = EXPERIENCE_RE.search(text)
    if match:
        return float(match.group(1))

    return 0.0


EMPLOYER_NOISE_RE = re.compile(
    r"google\s+cloud(?:\s+vision)?|linkedin\.com/\S*|github\.com/\S*|"
    r"https?://\S+|vercel\.app|openai\s+apis?",
    re.IGNORECASE,
)


def _find_tier_companies(text: str) -> list[str]:
    cleaned = EMPLOYER_NOISE_RE.sub(" ", text)
    lowered = cleaned.lower()
    found: list[str] = []
    for alias, canonical in known_company_aliases().items():
        if alias in {"linkedin", "twitter", "google"}:
            if alias == "google" and re.search(r"\bgoogle\s+(?:cloud|apis?)\b", text, re.I):
                continue
            if re.search(rf"\b{re.escape(alias)}\.com\b", lowered):
                continue
        if re.search(rf"\b{re.escape(alias)}\b", lowered):
            found.append(canonical)
    return found


def _extract_employers(sections: dict[str, str], full_text: str) -> tuple[str, list[str]]:
    experience_text = "\n".join(
        body for heading, body in sections.items() if EXPERIENCE_SECTION_RE.match(heading)
    )

    employers: list[str] = []
    current_company = ""

    if experience_text:
        scrubbed = "\n".join(
            line for line in experience_text.splitlines()
            if line.strip() and "http" not in line.lower() and ".com" not in line.lower()
        )
        tier_matches = _find_tier_companies(scrubbed)
        employers.extend(tier_matches)

        for line in scrubbed.splitlines():
            line = line.strip()
            if not line or line.startswith(("•", "-")):
                continue
            match = COMPANY_LINE_RE.match(line)
            if match:
                candidate = match.group(1).strip()
                if len(candidate) > 2 and candidate.lower() not in {"experience", "employment"}:
                    employers.append(candidate)

        if employers:
            current_company = employers[0]

    deduped: list[str] = []
    seen: set[str] = set()
    for employer in employers:
        key = employer.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(employer)

    return current_company, deduped


def load_profile_from_pdf(path: Path, normalizer: SkillNormalizer | None = None) -> UserProfile:
    normalizer = normalizer or SkillNormalizer()
    text = extract_pdf_text(path)
    if not text.strip():
        raise ValueError(f"Could not extract text from PDF: {path}")

    lines = _clean_lines(text)
    name, role, location = _parse_header(lines)
    sections = _split_sections(text)

    skills: dict[str, float] = {}
    for heading, body in sections.items():
        if SKILLS_SECTION_RE.match(heading):
            for skill, weight in _skills_from_section(body, normalizer, weight=1.5).items():
                skills[skill] = max(skills.get(skill, 0.0), weight)

    for skill, weight in _skills_from_section(text, normalizer, weight=1.0).items():
        skills[skill] = max(skills.get(skill, 0.0), weight)

    if not skills:
        raise ValueError(
            f"No recognizable skills found in PDF: {path}. "
            "Ensure the resume lists technical skills in plain text."
        )

    current_company, employers = _extract_employers(sections, text)
    has_work_experience = _has_work_experience(sections, employers)
    experience_years = (
        _parse_experience_years(text, sections) if has_work_experience else 0.0
    )

    summary_text = sections.get("professional summary", "") or sections.get("summary", "")
    work_preference = infer_work_preference(location=location, text=f"{summary_text}\n{text}")
    is_student, has_degree = infer_education_status(
        sections=sections,
        full_text=text,
        has_work_experience=has_work_experience,
        role=role,
    )
    degree_level = infer_degree_level(
        sections=sections,
        full_text=text,
        is_student=is_student,
        has_degree=has_degree,
    )
    degree_field = parse_degree_field(
        {},
        sections=sections,
        full_text=text,
        role=role,
    )

    return UserProfile(
        name=name,
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
