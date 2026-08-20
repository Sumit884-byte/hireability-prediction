"""Best-effort fetchers for LinkedIn, Internshala, and Glassdoor job listings."""

from __future__ import annotations

import html
import re
import time
from datetime import date, datetime
from html import unescape
from urllib.parse import urljoin

import requests
from dateutil import parser as date_parser

from hireability.config import (
    BROWSER_USER_AGENT,
    GLASSDOOR_MAX_PAGES,
    GLASSDOOR_SEARCH_TERMS,
    INTERNSHALA_BASE_URL,
    INTERNSHALA_MAX_PAGES,
    INTERNSHALA_SEARCH_SLUGS,
    LINKEDIN_JOB_DETAIL_URL,
    LINKEDIN_JOBS_API_URL,
    LINKEDIN_MAX_DETAILS,
    LINKEDIN_MAX_RESULTS,
    LINKEDIN_SEARCH_KEYWORDS,
    LINKEDIN_SEARCH_LOCATION,
    SCRAPE_REQUEST_DELAY_SEC,
)
from hireability.jobs.salary_parse import ParsedSalary, salary_from_job_text
from hireability.models import JobPost

HTML_TAG_RE = re.compile(r"<[^>]+>")
CARD_SPLIT_RE = re.compile(r"<li>\s*", re.IGNORECASE)
INTERNSHIP_SPLIT_RE = re.compile(r'internshipId="(?P<id>\d+)"', re.IGNORECASE)


def _browser_headers(*, referer: str = "https://www.google.com/") -> dict[str, str]:
    return {
        "User-Agent": BROWSER_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": referer,
        "sec-ch-ua": '"Not_A Brand";v="8", "Chromium";v="120"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Linux"',
    }


def _strip_html(text: str) -> str:
    cleaned = HTML_TAG_RE.sub(" ", text or "")
    return re.sub(r"\s+", " ", unescape(cleaned)).strip()


def _parse_posted_date(value: str | None) -> date:
    if not value:
        return datetime.utcnow().date()
    try:
        return date_parser.parse(str(value)).date()
    except (ValueError, TypeError, OverflowError):
        return datetime.utcnow().date()


def _request_text(url: str, *, params: dict | None = None, referer: str | None = None) -> str:
    headers = _browser_headers(referer=referer or "https://www.google.com/")
    response = requests.get(url, params=params, headers=headers, timeout=30)
    response.raise_for_status()
    return response.text


def _attach_salary(
    post: JobPost,
    *,
    salary_min: float | None = None,
    salary_max: float | None = None,
    salary_currency: str = "",
    salary_period: str = "",
    extra_text: str = "",
) -> JobPost:
    if salary_min is not None and salary_max is not None:
        post.salary_min = salary_min
        post.salary_max = salary_max
        post.salary_currency = salary_currency
        post.salary_period = salary_period
        return post

    parsed = salary_from_job_text(post.description, extra_text, post.title)
    if parsed:
        post.salary_min = parsed.salary_min
        post.salary_max = parsed.salary_max
        post.salary_currency = parsed.currency
        post.salary_period = parsed.period
    return post


def _parse_linkedin_card(chunk: str) -> JobPost | None:
    title_match = re.search(r"base-search-card__title[^>]*>\s*([^<]+?)\s*<", chunk)
    company_match = re.search(
        r"base-search-card__subtitle[^>]*>.*?hidden-nested-link[^>]*>\s*([^<]+?)\s*<",
        chunk,
        re.DOTALL,
    )
    location_match = re.search(r"job-search-card__location[^>]*>\s*([^<]+?)\s*<", chunk)
    url_match = re.search(r'base-card__full-link[^>]*href="([^"]+)"', chunk)
    date_match = re.search(r'<time[^>]*datetime="([^"]+)"', chunk)
    entity_match = re.search(r'data-entity-urn="urn:li:jobPosting:(\d+)"', chunk)

    if not title_match or not url_match:
        return None

    title = _strip_html(title_match.group(1))
    company = _strip_html(company_match.group(1)) if company_match else ""
    location = _strip_html(location_match.group(1)) if location_match else ""
    job_url = html.unescape(url_match.group(1))
    posted = _parse_posted_date(date_match.group(1) if date_match else None)
    entity_id = entity_match.group(1) if entity_match else ""

    description = f"{title} at {company}. Location: {location}."
    return JobPost(
        title=title,
        company=company,
        posted_date=posted,
        description=description,
        tags=["linkedin"],
        category="",
        location=location,
        source="linkedin",
        url=job_url,
        description_original=entity_id or None,
    )


def _linkedin_job_detail(entity_id: str) -> tuple[str, ParsedSalary | None]:
    if not entity_id:
        return "", None
    try:
        text = _request_text(
            f"{LINKEDIN_JOB_DETAIL_URL}/{entity_id}",
            referer=LINKEDIN_JOBS_API_URL,
        )
    except requests.RequestException:
        return "", None

    desc_match = re.search(
        r"show-more-less-html__markup[^>]*>(.*?)</div>",
        text,
        re.DOTALL,
    )
    description = _strip_html(desc_match.group(1)) if desc_match else ""
    salary = salary_from_job_text(description, text)
    return description, salary


def fetch_linkedin_jobs(
    *,
    keywords: str | None = None,
    location: str | None = None,
    max_results: int = LINKEDIN_MAX_RESULTS,
    max_details: int = LINKEDIN_MAX_DETAILS,
) -> list[JobPost]:
    keywords = keywords or LINKEDIN_SEARCH_KEYWORDS
    location = location or LINKEDIN_SEARCH_LOCATION
    posts: list[JobPost] = []
    seen_urls: set[str] = set()

    for start in range(0, max_results, 25):
        try:
            page = _request_text(
                LINKEDIN_JOBS_API_URL,
                params={"keywords": keywords, "location": location, "start": start},
            )
        except requests.RequestException:
            break

        cards = CARD_SPLIT_RE.split(page)[1:]
        if not cards:
            break

        for chunk in cards:
            post = _parse_linkedin_card(chunk)
            if not post or post.url in seen_urls:
                continue
            seen_urls.add(post.url)
            posts.append(post)
            if len(posts) >= max_results:
                break

        if len(cards) < 10:
            break
        time.sleep(SCRAPE_REQUEST_DELAY_SEC)

    details_fetched = 0
    for post in posts:
        if details_fetched >= max_details:
            break
        entity_id = post.description_original or ""
        if not entity_id:
            match = re.search(r"jobs/view/[^/]*-(\d+)", post.url)
            entity_id = match.group(1) if match else ""
        description, salary = _linkedin_job_detail(entity_id)
        if description:
            post.description = description
        if salary:
            post.salary_min = salary.salary_min
            post.salary_max = salary.salary_max
            post.salary_currency = salary.currency
            post.salary_period = salary.period
        post.description_original = None
        details_fetched += 1
        time.sleep(SCRAPE_REQUEST_DELAY_SEC)

    return posts


def _parse_internshala_block(body: str, slug: str) -> JobPost | None:
    title_match = re.search(r'class="job-title-href"[^>]*href="([^"]+)"[^>]*>([^<]+)<', body)
    company_match = re.search(r'class="company-name"[^>]*>\s*([^<]+?)\s*<', body)
    location_match = re.search(r'class="row-1-item locations".*?<span>\s*([^<]+?)\s*<', body, re.DOTALL)
    stipend_match = re.search(r'class=[\'"]stipend[\'"][^>]*>([^<]+)<', body)
    duration_match = re.search(r'class=[\'"]row-1-item[\'"][^>]*>\s*<i class="ic-16-calendar"></i>\s*<span>\s*([^<]+?)\s*<', body, re.DOTALL)

    if not title_match:
        return None

    rel_url = title_match.group(1).strip()
    title = _strip_html(title_match.group(2))
    company = _strip_html(company_match.group(1)) if company_match else ""
    location = _strip_html(location_match.group(1)) if location_match else "India"
    stipend = _strip_html(stipend_match.group(1)) if stipend_match else ""
    duration = _strip_html(duration_match.group(1)) if duration_match else ""

    url = urljoin(INTERNSHALA_BASE_URL, rel_url)
    description = (
        f"Internship: {title} at {company}. Location: {location}. "
        f"Duration: {duration or 'not specified'}. Stipend: {stipend or 'not listed'}."
    )
    post = JobPost(
        title=title,
        company=company,
        posted_date=datetime.utcnow().date(),
        description=description,
        tags=["internship", slug.replace("-", "_")],
        category="internship",
        location=location,
        source="internshala",
        url=url,
    )
    stipend_blob = stipend
    if stipend and re.search(r"[\d,]", stipend) and "month" not in stipend.lower():
        stipend_blob = f"{stipend} /month"
    return _attach_salary(post, extra_text=stipend_blob)


def fetch_internshala_jobs(
    *,
    slugs: tuple[str, ...] = INTERNSHALA_SEARCH_SLUGS,
    max_pages: int = INTERNSHALA_MAX_PAGES,
) -> list[JobPost]:
    posts: list[JobPost] = []
    seen_urls: set[str] = set()

    for slug in slugs:
        for page in range(1, max_pages + 1):
            path = f"/internships/{slug}"
            if page > 1:
                path = f"{path}/page-{page}"
            try:
                text = _request_text(urljoin(INTERNSHALA_BASE_URL, path))
            except requests.RequestException:
                break

            parts = INTERNSHIP_SPLIT_RE.split(text, maxsplit=0)
            if len(parts) < 2:
                break

            for body in parts[1:]:
                post = _parse_internshala_block(body, slug)
                if not post or post.url in seen_urls:
                    continue
                seen_urls.add(post.url)
                posts.append(post)

            time.sleep(SCRAPE_REQUEST_DELAY_SEC)

    return posts


def _glassdoor_salary_from_json_blob(blob: str) -> ParsedSalary | None:
    min_match = re.search(r'"minSalary"\s*:\s*(\d+(?:\.\d+)?)', blob)
    max_match = re.search(r'"maxSalary"\s*:\s*(\d+(?:\.\d+)?)', blob)
    cur_match = re.search(r'"currency"\s*:\s*"([A-Z]{3})"', blob)
    period_match = re.search(r'"payPeriod"\s*:\s*"([A-Z_]+)"', blob)
    if not min_match or not max_match:
        return None

    lo = float(min_match.group(1))
    hi = float(max_match.group(1))
    currency = cur_match.group(1) if cur_match else "USD"
    period_raw = (period_match.group(1) if period_match else "ANNUAL").lower()
    period = "year" if "annual" in period_raw or period_raw == "year" else "month"
    return ParsedSalary(lo, hi, currency, period)


def _parse_glassdoor_cards(page_html: str) -> list[JobPost]:
    posts: list[JobPost] = []
    seen: set[str] = set()

    for chunk in page_html.split("JobCard_jobTitle__")[1:]:
        title_match = re.search(r"[^>]*>([^<]+)<", chunk)
        company_match = re.search(r"compactEmployerName[^>]*>\s*([^<]+?)\s*<", chunk)
        location_match = re.search(r"JobCard_location[^>]*>\s*([^<]+?)\s*<", chunk)
        salary_match = re.search(r"JobCard_salaryEstimate[^>]*>\s*([^<]+?)\s*<", chunk)
        listing_match = re.search(r"jobListingId=(\d+)", chunk)

        if not title_match:
            continue

        title = _strip_html(title_match.group(1))
        company = _strip_html(company_match.group(1)) if company_match else ""
        location = _strip_html(location_match.group(1)) if location_match else ""
        salary_text = _strip_html(salary_match.group(1)) if salary_match else ""
        listing_id = listing_match.group(1) if listing_match else ""
        key = f"{title}|{company}|{location}"
        if key in seen:
            continue
        seen.add(key)

        url = f"https://www.glassdoor.com/job-listing/?jl={listing_id}" if listing_id else ""
        salary = salary_from_job_text(salary_text) or _glassdoor_salary_from_json_blob(chunk)
        description = f"{title} at {company}. Location: {location}."
        if salary_text:
            description += f" Salary estimate: {salary_text}."

        post = JobPost(
            title=title,
            company=company,
            posted_date=datetime.utcnow().date(),
            description=description,
            tags=["glassdoor"],
            category="",
            location=location,
            source="glassdoor",
            url=url,
        )
        if salary:
            post.salary_min = salary.salary_min
            post.salary_max = salary.salary_max
            post.salary_currency = salary.currency
            post.salary_period = salary.period
        posts.append(post)

    return posts


def fetch_glassdoor_jobs(
    *,
    search_terms: tuple[str, ...] = GLASSDOOR_SEARCH_TERMS,
    max_pages: int = GLASSDOOR_MAX_PAGES,
) -> list[JobPost]:
    posts: list[JobPost] = []
    seen: set[str] = set()

    for term in search_terms:
        slug = term.strip().lower().replace(" ", "-")
        for page in range(1, max_pages + 1):
            if page == 1:
                path = f"https://www.glassdoor.com/Job/{slug}-jobs-SRCH_KO0,{len(term)}.htm"
            else:
                path = (
                    f"https://www.glassdoor.com/Job/{slug}-jobs-SRCH_KO0,{len(term)}_IP{page}.htm"
                )
            try:
                text = _request_text(path)
            except requests.RequestException:
                break

            batch = _parse_glassdoor_cards(text)
            if not batch:
                break

            for post in batch:
                key = f"{post.title}|{post.company}|{post.location}"
                if key in seen:
                    continue
                seen.add(key)
                posts.append(post)

            time.sleep(SCRAPE_REQUEST_DELAY_SEC)

    return posts
