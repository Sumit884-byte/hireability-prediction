"""Extract structured salary ranges from free-text job descriptions."""

from __future__ import annotations

import re
from dataclasses import dataclass

LPA_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*[-–to]+\s*(\d+(?:\.\d+)?)\s*(?:lpa|lakhs?)\b",
    re.IGNORECASE,
)
SINGLE_LPA_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:lpa|lakhs?)\b",
    re.IGNORECASE,
)
CURRENCY_RANGE_RE = re.compile(
    r"(?P<cur>[$€£₹]|USD|INR|EUR|GBP)\s*"
    r"(?P<lo>[\d,]+(?:\.\d+)?)\s*(?:k|K)?\s*[-–to]+\s*"
    r"(?P<cur2>[$€£₹]|USD|INR|EUR|GBP)?\s*"
    r"(?P<hi>[\d,]+(?:\.\d+)?)\s*(?:k|K)?"
    r"(?:\s*/\s*(?P<period>month|year|yr|annum|hour|hr|week))?",
    re.IGNORECASE,
)
RANGE_NO_CUR_RE = re.compile(
    r"(?P<lo>[\d,]+)\s*[-–to]+\s*(?P<hi>[\d,]+)"
    r"(?:\s*/\s*(?P<period>month|year|yr|annum))?",
    re.IGNORECASE,
)
STIPEND_RE = re.compile(
    r"(?:stipend|unpaid|not\s+paid)",
    re.IGNORECASE,
)
UNPAID_RE = re.compile(r"\bunpaid\b", re.IGNORECASE)

CURRENCY_MAP = {
    "$": "USD",
    "usd": "USD",
    "€": "EUR",
    "eur": "EUR",
    "£": "GBP",
    "gbp": "GBP",
    "₹": "INR",
    "inr": "INR",
}


@dataclass(frozen=True)
class ParsedSalary:
    salary_min: float
    salary_max: float
    currency: str
    period: str


def _to_number(raw: str, *, had_k_suffix: bool = False) -> float:
    cleaned = raw.replace(",", "").strip()
    value = float(cleaned)
    if had_k_suffix or (value < 1000 and "." not in cleaned):
        if value < 1000:
            value *= 1000
    return value


def _normalize_currency(token: str | None) -> str:
    if not token:
        return ""
    return CURRENCY_MAP.get(token.strip().lower(), token.strip().upper())


def _normalize_period(token: str | None, *, currency: str, amount: float) -> str:
    if not token:
        if currency == "INR" and amount < 500_000:
            return "month"
        return "year"
    cleaned = token.strip().lower()
    if cleaned in {"yr", "annum", "annual", "year", "yearly"}:
        return "year"
    if cleaned in {"hr", "hour", "hourly"}:
        return "hour"
    if cleaned in {"week", "weekly"}:
        return "week"
    return "month"


def _parse_indian_shorthand(text: str) -> ParsedSalary | None:
    match = re.search(
        r"₹\s*(?P<lo>[\d.]+)\s*(?P<lok>K|L)?\s*[-–to]+\s*₹?\s*(?P<hi>[\d.]+)\s*(?P<hik>K|L)?",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None

    def _unit(value: str, suffix: str | None) -> float:
        amount = float(value)
        if suffix and suffix.upper() == "K":
            return amount * 1000
        if suffix and suffix.upper() == "L":
            return amount * 100_000
        if amount < 1000:
            return amount * 100_000
        return amount

    lo = _unit(match.group("lo"), match.group("lok"))
    hi = _unit(match.group("hi"), match.group("hik"))
    period = "month" if hi < 200_000 else "year"
    return ParsedSalary(min(lo, hi), max(lo, hi), "INR", period)


def parse_salary_text(text: str) -> ParsedSalary | None:
    if not text or not text.strip():
        return None

    indian = _parse_indian_shorthand(text)
    if indian:
        return indian

    if UNPAID_RE.search(text) and not re.search(r"[\d]{3,}", text):
        return ParsedSalary(0.0, 0.0, "INR", "month")

    match = LPA_RE.search(text)
    if match:
        lo = float(match.group(1)) * 100_000
        hi = float(match.group(2)) * 100_000
        return ParsedSalary(lo, hi, "INR", "year")

    match = SINGLE_LPA_RE.search(text)
    if match:
        val = float(match.group(1)) * 100_000
        return ParsedSalary(val * 0.9, val * 1.1, "INR", "year")

    match = CURRENCY_RANGE_RE.search(text)
    if match:
        cur = _normalize_currency(match.group("cur") or match.group("cur2"))
        lo_raw = match.group("lo")
        hi_raw = match.group("hi")
        lo_k = lo_raw.lower().endswith("k")
        hi_k = hi_raw.lower().endswith("k")
        lo = _to_number(lo_raw.rstrip("kK"), had_k_suffix=lo_k)
        hi = _to_number(hi_raw.rstrip("kK"), had_k_suffix=hi_k)
        period = _normalize_period(match.group("period"), currency=cur, amount=max(lo, hi))
        return ParsedSalary(min(lo, hi), max(lo, hi), cur, period)

    match = RANGE_NO_CUR_RE.search(text)
    if match:
        lo = _to_number(match.group("lo"))
        hi = _to_number(match.group("hi"))
        if hi > lo and hi < 10_000_000:
            period = _normalize_period(match.group("period"), currency="INR", amount=hi)
            currency = "INR" if hi < 500_000 else "USD"
            return ParsedSalary(lo, hi, currency, period)

    return None


def salary_from_job_text(*parts: str) -> ParsedSalary | None:
    blob = " ".join(part for part in parts if part).strip()
    if STIPEND_RE.search(blob):
        parsed = parse_salary_text(blob)
        if parsed:
            return parsed
        if UNPAID_RE.search(blob):
            return ParsedSalary(0.0, 0.0, "INR", "month")
    return parse_salary_text(blob)
