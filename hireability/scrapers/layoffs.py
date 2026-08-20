import json
import re
from datetime import date, datetime

import requests
from dateutil.relativedelta import relativedelta

from hireability.config import (
    LAYOFFS_CHART_API,
    SEED_LAYOFFS_PATH,
    USER_AGENT,
)
from hireability.models import LayoffEvent

MONTH_LABEL_RE = re.compile(r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) '(\d{2})$")
MONTH_MAP = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}


def _parse_month_label(label: str) -> date | None:
    match = MONTH_LABEL_RE.match(label.strip())
    if not match:
        return None
    month = MONTH_MAP[match.group(1)]
    year = 2000 + int(match.group(2))
    return date(year, month, 1)


def _load_seed_events() -> list[LayoffEvent]:
    if not SEED_LAYOFFS_PATH.exists():
        return []
    with SEED_LAYOFFS_PATH.open(encoding="utf-8") as handle:
        rows = json.load(handle)
    return [
        LayoffEvent(
            company=row["company"],
            event_date=date.fromisoformat(row["event_date"]),
            headcount=int(row["headcount"]),
            industry=row.get("industry", "Technology"),
            country=row.get("country", ""),
            source="seed",
        )
        for row in rows
    ]


def _fetch_monthly_macro_events() -> list[LayoffEvent]:
    response = requests.get(
        LAYOFFS_CHART_API,
        params={"view": "monthly"},
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()

    events: list[LayoffEvent] = []
    labels = payload.get("labels", [])
    employees = payload.get("employees", [])
    for label, headcount in zip(labels, employees):
        month_start = _parse_month_label(label)
        if not month_start or not headcount:
            continue
        events.append(
            LayoffEvent(
                company=f"Tech sector aggregate ({label})",
                event_date=month_start,
                headcount=int(headcount),
                industry="Technology",
                country="Global",
                source="layoffs.fyi-chart",
            )
        )
    return events


def fetch_layoffs(include_seed: bool = True) -> list[LayoffEvent]:
    """Fetch layoff supply signals from layoffs.fyi chart API plus seed events."""
    events: list[LayoffEvent] = []
    try:
        events.extend(_fetch_monthly_macro_events())
    except requests.RequestException as exc:
        print(f"Warning: layoffs chart API unavailable ({exc}). Using seed data only.")

    if include_seed:
        events.extend(_load_seed_events())

    # Deduplicate by company + date + source.
    seen: set[tuple] = set()
    unique: list[LayoffEvent] = []
    for event in events:
        key = (event.company, event.event_date, event.source)
        if key in seen:
            continue
        seen.add(key)
        unique.append(event)

    unique.sort(key=lambda item: item.event_date, reverse=True)
    return unique


def recent_cutoff(days: int = 90) -> date:
    return (datetime.utcnow().date() - relativedelta(days=days))
