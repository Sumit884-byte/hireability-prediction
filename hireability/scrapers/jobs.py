import re
from collections.abc import Callable
from datetime import date, datetime

import requests
from dateutil import parser as date_parser

from hireability.config import (
    ARBEITNOW_API_URL,
    ARBEITNOW_MAX_PAGES,
    HIMALAYAS_API_URL,
    HIMALAYAS_MAX_PAGES,
    HIMALAYAS_PAGE_SIZE,
    JOB_SOURCES,
    JOBICY_API_URL,
    REMOTEOK_API_URL,
    REMOTIVE_API_URL,
    USER_AGENT,
)
from hireability.jobs.salary_parse import salary_from_job_text
from hireability.models import JobPost

HTML_TAG_RE = re.compile(r"<[^>]+>")
JobFetcher = Callable[[], list[JobPost]]


def _strip_html(text: str) -> str:
    return HTML_TAG_RE.sub(" ", text or "").strip()


def _parse_posted_date(value: str | int | float | None) -> date:
    if value is None or value == "":
        return datetime.utcnow().date()
    if isinstance(value, (int, float)):
        return datetime.utcfromtimestamp(value).date()
    try:
        return date_parser.parse(str(value)).date()
    except (ValueError, TypeError, OverflowError):
        return datetime.utcnow().date()


def _request_json(url: str, params: dict | None = None) -> dict | list:
    response = requests.get(
        url,
        params=params,
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def _as_tags(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(tag).strip() for tag in value if str(tag).strip()]
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return [str(value).strip()]


def _as_text(value) -> str:
    if not value:
        return ""
    if isinstance(value, list):
        return ", ".join(_as_tags(value))
    return str(value).strip()


def _fetch_remotive() -> list[JobPost]:
    payload = _request_json(REMOTIVE_API_URL)
    posts: list[JobPost] = []
    for row in payload.get("jobs", []):
        posts.append(
            JobPost(
                title=row.get("title", "").strip(),
                company=row.get("company_name", "").strip(),
                posted_date=_parse_posted_date(row.get("publication_date")),
                description=_strip_html(row.get("description", "")),
                tags=_as_tags(row.get("tags")),
                category=row.get("category", "").strip(),
                location=row.get("candidate_required_location", "").strip(),
                source="remotive",
                url=row.get("url", "").strip(),
            )
        )
    return posts


def _fetch_arbeitnow(max_pages: int = ARBEITNOW_MAX_PAGES) -> list[JobPost]:
    posts: list[JobPost] = []
    for page in range(1, max_pages + 1):
        payload = _request_json(ARBEITNOW_API_URL, params={"page": page})
        rows = payload.get("data", [])
        if not rows:
            break
        for row in rows:
            posts.append(
                JobPost(
                    title=row.get("title", "").strip(),
                    company=row.get("company_name", "").strip(),
                    posted_date=_parse_posted_date(row.get("created_at")),
                    description=_strip_html(row.get("description", "")),
                    tags=_as_tags(row.get("tags")) + _as_tags(row.get("job_types")),
                    category="",
                    location=row.get("location", "").strip(),
                    source="arbeitnow",
                    url=row.get("url", "").strip(),
                )
            )
        if not payload.get("links", {}).get("next"):
            break
    return posts


def _fetch_remoteok() -> list[JobPost]:
    payload = _request_json(REMOTEOK_API_URL)
    if not isinstance(payload, list):
        return []

    posts: list[JobPost] = []
    for row in payload:
        if "position" not in row:
            continue
        description = _strip_html(row.get("description", ""))
        salary_raw = str(row.get("salary") or "").strip()
        post = JobPost(
            title=row.get("position", "").strip(),
            company=row.get("company", "").strip(),
            posted_date=_parse_posted_date(row.get("date") or row.get("epoch")),
            description=description,
            tags=_as_tags(row.get("tags")),
            category="",
            location=row.get("location", "").strip(),
            source="remoteok",
            url=(row.get("apply_url") or row.get("url") or "").strip(),
        )
        parsed = salary_from_job_text(salary_raw, description, post.title)
        if parsed:
            post.salary_min = parsed.salary_min
            post.salary_max = parsed.salary_max
            post.salary_currency = parsed.currency
            post.salary_period = parsed.period
        posts.append(post)
    return posts


def _fetch_jobicy() -> list[JobPost]:
    payload = _request_json(JOBICY_API_URL, params={"count": 100})
    posts: list[JobPost] = []
    for row in payload.get("jobs", []):
        description = _strip_html(
            row.get("jobDescription") or row.get("jobExcerpt") or ""
        )
        posts.append(
            JobPost(
                title=row.get("jobTitle", "").strip(),
                company=row.get("companyName", "").strip(),
                posted_date=_parse_posted_date(row.get("pubDate")),
                description=description,
                tags=_as_tags(
                    [
                        row.get("jobIndustry"),
                        row.get("jobType"),
                        row.get("jobGeo"),
                        row.get("jobLevel"),
                    ]
                ),
                category=_as_text(row.get("jobIndustry")),
                location=_as_text(row.get("jobGeo")),
                source="jobicy",
                url=row.get("url", "").strip(),
            )
        )
    return posts


def _fetch_himalayas(max_pages: int = HIMALAYAS_MAX_PAGES) -> list[JobPost]:
    posts: list[JobPost] = []
    for page in range(max_pages):
        payload = _request_json(
            HIMALAYAS_API_URL,
            params={
                "limit": HIMALAYAS_PAGE_SIZE,
                "offset": page * HIMALAYAS_PAGE_SIZE,
            },
        )
        rows = payload.get("jobs", [])
        if not rows:
            break

        for row in rows:
            description = _strip_html(row.get("description") or row.get("excerpt") or "")
            posts.append(
                JobPost(
                    title=row.get("title", "").strip(),
                    company=row.get("companyName", "").strip(),
                    posted_date=_parse_posted_date(row.get("pubDate")),
                    description=description,
                    tags=_as_tags(row.get("categories"))
                    + _as_tags(row.get("parentCategories"))
                    + _as_tags(row.get("seniority"))
                    + _as_tags(row.get("employmentType")),
                    category=", ".join(_as_tags(row.get("parentCategories"))),
                    location=", ".join(_as_tags(row.get("locationRestrictions"))),
                    source="himalayas",
                    url=(row.get("applicationLink") or row.get("guid") or "").strip(),
                )
            )
    return posts


def _fetch_linkedin() -> list[JobPost]:
    from hireability.scrapers.board_scrapers import fetch_linkedin_jobs

    return fetch_linkedin_jobs()


def _fetch_internshala() -> list[JobPost]:
    from hireability.scrapers.board_scrapers import fetch_internshala_jobs

    return fetch_internshala_jobs()


def _fetch_glassdoor() -> list[JobPost]:
    from hireability.scrapers.board_scrapers import fetch_glassdoor_jobs

    return fetch_glassdoor_jobs()


_SOURCE_FETCHERS: dict[str, JobFetcher] = {
    "remotive": _fetch_remotive,
    "arbeitnow": _fetch_arbeitnow,
    "remoteok": _fetch_remoteok,
    "jobicy": _fetch_jobicy,
    "himalayas": lambda: _fetch_himalayas(),
    "linkedin": _fetch_linkedin,
    "internshala": _fetch_internshala,
    "glassdoor": _fetch_glassdoor,
}


def available_sources() -> tuple[str, ...]:
    return JOB_SOURCES


def fetch_jobs_by_source(
    sources: list[str] | None = None,
    himalayas_max_pages: int = HIMALAYAS_MAX_PAGES,
    arbeitnow_max_pages: int = ARBEITNOW_MAX_PAGES,
) -> dict[str, list[JobPost]]:
    """Fetch jobs grouped by source, for per-source ingest reporting."""
    selected = sources or list(JOB_SOURCES)
    unknown = [name for name in selected if name not in _SOURCE_FETCHERS]
    if unknown:
        raise ValueError(
            f"Unknown job sources: {', '.join(unknown)}. "
            f"Available: {', '.join(JOB_SOURCES)}"
        )

    grouped: dict[str, list[JobPost]] = {}
    for name in selected:
        try:
            if name == "himalayas":
                grouped[name] = _fetch_himalayas(max_pages=himalayas_max_pages)
            elif name == "arbeitnow":
                grouped[name] = _fetch_arbeitnow(max_pages=arbeitnow_max_pages)
            else:
                grouped[name] = _SOURCE_FETCHERS[name]()
        except requests.RequestException as exc:
            print(f"Warning: {name} fetch failed ({exc}). Skipping.")
            grouped[name] = []

    return grouped


def fetch_jobs(
    sources: list[str] | None = None,
    limit: int | None = None,
    himalayas_max_pages: int = HIMALAYAS_MAX_PAGES,
) -> list[JobPost]:
    """Fetch active job posts from one or more public job board APIs."""
    grouped = fetch_jobs_by_source(
        sources=sources,
        himalayas_max_pages=himalayas_max_pages,
    )
    posts: list[JobPost] = []
    for source_posts in grouped.values():
        posts.extend(source_posts)

    if limit is not None:
        posts = posts[:limit]
    return posts
