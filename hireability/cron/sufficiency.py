"""Data depth milestones for reliable 30/90-day scoring."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from hireability.config import (
    BASELINE_WINDOW_DAYS,
    CURRENT_WINDOW_DAYS,
    CRON_STATE_PATH,
    MIN_JOB_POSTS,
    MIN_LAYOFF_EVENTS,
    MIN_SCRAPED_DAYS,
)
from hireability.market.daily import market_daily_stats
from hireability.storage import counts, init_db


@dataclass
class SufficiencyReport:
    sufficient: bool
    newly_sufficient: bool
    checks: dict[str, bool]
    metrics: dict[str, int | str | None]
    message: str


def _default_state() -> dict:
    return {
        "sufficient_notified": False,
        "sufficient_since": None,
        "last_run_at": None,
        "last_run_ok": None,
        "run_count": 0,
    }


def load_cron_state(path: Path = CRON_STATE_PATH) -> dict:
    if not path.exists():
        return _default_state()
    with path.open(encoding="utf-8") as handle:
        return {**_default_state(), **json.load(handle)}


def already_ran_today(state: dict | None = None) -> bool:
    """True if a successful ingest already ran today (local date)."""
    state = state or load_cron_state()
    if not state.get("last_run_ok"):
        return False

    last = state.get("last_run_at")
    if not last:
        return False

    try:
        last_dt = datetime.fromisoformat(last)
    except ValueError:
        return False

    if last_dt.tzinfo is None:
        last_dt = last_dt.replace(tzinfo=timezone.utc)

    today = datetime.now().astimezone().date()
    return last_dt.astimezone().date() == today


def save_cron_state(state: dict, path: Path = CRON_STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2)


def check_sufficiency(state: dict | None = None) -> SufficiencyReport:
    init_db()
    state = state or load_cron_state()
    totals = counts()
    market = market_daily_stats()

    min_market_days = BASELINE_WINDOW_DAYS + CURRENT_WINDOW_DAYS
    metrics = {
        "job_posts": totals["job_posts"],
        "layoff_events": totals["layoff_events"],
        "market_days": market["total_days"],
        "scraped_days": market["scraped_days"],
        "seeded_days": market["seeded_days"],
        "market_min_date": market["min_date"],
        "market_max_date": market["max_date"],
    }

    checks = {
        "job_posts": totals["job_posts"] >= MIN_JOB_POSTS,
        "layoff_events": totals["layoff_events"] >= MIN_LAYOFF_EVENTS,
        "market_timeline": market["total_days"] >= min_market_days,
        "live_scrape_depth": market["scraped_days"] >= MIN_SCRAPED_DAYS,
    }
    sufficient = all(checks.values())
    newly_sufficient = sufficient and not state.get("sufficient_notified", False)

    passed = sum(checks.values())
    total = len(checks)
    if sufficient:
        message = (
            f"Data collection is sufficient ({passed}/{total} checks). "
            f"{market['scraped_days']} live scrape days, "
            f"{totals['job_posts']} jobs, {market['total_days']} day timeline."
        )
    else:
        missing = [name for name, ok in checks.items() if not ok]
        message = (
            f"Data collection in progress ({passed}/{total} checks). "
            f"Still need: {', '.join(missing)}."
        )

    return SufficiencyReport(
        sufficient=sufficient,
        newly_sufficient=newly_sufficient,
        checks=checks,
        metrics=metrics,
        message=message,
    )


def record_run(
    *,
    ok: bool,
    report: SufficiencyReport,
    state: dict | None = None,
) -> dict:
    state = dict(state or load_cron_state())
    state["last_run_at"] = datetime.utcnow().isoformat(timespec="seconds")
    state["last_run_ok"] = ok
    state["run_count"] = int(state.get("run_count", 0)) + 1
    state["last_metrics"] = report.metrics
    state["last_checks"] = report.checks

    if report.newly_sufficient:
        state["sufficient_notified"] = True
        state["sufficient_since"] = state["last_run_at"]

    save_cron_state(state)
    return state
