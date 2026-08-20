import hashlib
import re
from collections import defaultdict

from hireability.models import JobPost

_WS_RE = re.compile(r"\s+")


def _normalize(value: str) -> str:
    return _WS_RE.sub(" ", (value or "").strip().lower())


def job_fingerprint(
    title: str,
    company: str,
    description: str,
    *,
    desc_limit: int = 1000,
) -> str:
    """Stable identity for a job posting based on content, not URL."""
    payload = "|".join(
        [
            _normalize(title),
            _normalize(company),
            _normalize(description)[:desc_limit],
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def fingerprint_for_post(post: JobPost) -> str:
    return job_fingerprint(post.title, post.company, post.description)


def find_duplicate_groups(posts: list[JobPost]) -> dict[str, list[JobPost]]:
    groups: dict[str, list[JobPost]] = defaultdict(list)
    for post in posts:
        groups[fingerprint_for_post(post)].append(post)
    return {key: items for key, items in groups.items() if len(items) > 1}


def dedupe_job_posts(posts: list[JobPost]) -> tuple[list[JobPost], int]:
    """Return unique posts and the number of duplicates removed."""
    unique: list[JobPost] = []
    seen: set[str] = set()
    removed = 0

    for post in posts:
        fp = fingerprint_for_post(post)
        if fp in seen:
            removed += 1
            continue
        seen.add(fp)
        unique.append(post)

    return unique, removed
