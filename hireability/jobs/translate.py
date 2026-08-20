"""Free translation of job text to English (Google Translate via deep-translator)."""

from __future__ import annotations

import os
import re
import time

from hireability.models import JobPost

_ASCII_HEAVY_RE = re.compile(r"[a-zA-Z]")
_CHUNK_SIZE = 4000
_TRANSLATE_ENABLED = os.environ.get("HIREABILITY_TRANSLATE", "1") != "0"


def translation_enabled() -> bool:
    return _TRANSLATE_ENABLED


def _ascii_ratio(text: str) -> float:
    letters = len(_ASCII_HEAVY_RE.findall(text))
    return letters / max(len(text), 1)


def needs_translation(text: str) -> bool:
    cleaned = (text or "").strip()
    if len(cleaned) < 24:
        return False
    if _ascii_ratio(cleaned) > 0.82:
        return False
    try:
        from langdetect import LangDetectException, detect

        return detect(cleaned) != "en"
    except (LangDetectException, Exception):
        return _ascii_ratio(cleaned) < 0.55


def _translate_chunk(text: str) -> str:
    from deep_translator import GoogleTranslator

    return GoogleTranslator(source="auto", target="en").translate(text)


def translate_to_english(text: str) -> str:
    cleaned = (text or "").strip()
    if not cleaned or not translation_enabled():
        return text
    if not needs_translation(cleaned):
        return text

    try:
        if len(cleaned) <= _CHUNK_SIZE:
            translated = _translate_chunk(cleaned)
            return translated or text

        parts: list[str] = []
        for start in range(0, len(cleaned), _CHUNK_SIZE):
            chunk = cleaned[start : start + _CHUNK_SIZE]
            parts.append(_translate_chunk(chunk))
            time.sleep(0.15)
        joined = " ".join(part for part in parts if part)
        return joined or text
    except Exception:
        return text


def localize_job_text(
    *,
    title: str,
    description: str,
) -> tuple[str, str, str | None, str | None]:
    """
    Return (title_en, description_en, title_original, description_original).

    Originals are set only when text was translated.
    """
    title_en = translate_to_english(title)
    desc_en = translate_to_english(description)
    title_original = title if title_en != title else None
    desc_original = description if desc_en != description else None
    return title_en, desc_en, title_original, desc_original


def localize_job_post(post: JobPost) -> JobPost:
    title_en, desc_en, title_original, desc_original = localize_job_text(
        title=post.title,
        description=post.description,
    )
    return JobPost(
        title=title_en,
        company=post.company,
        posted_date=post.posted_date,
        description=desc_en,
        tags=post.tags,
        category=post.category,
        location=post.location,
        source=post.source,
        url=post.url,
        content_hash=post.content_hash,
        first_seen=post.first_seen,
        last_seen=post.last_seen,
        sighting_days=post.sighting_days,
        title_original=title_original or getattr(post, "title_original", None),
        description_original=desc_original or getattr(post, "description_original", None),
    )
