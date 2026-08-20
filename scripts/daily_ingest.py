#!/usr/bin/env python3
"""
Daily ingest entrypoint: fetch market data and notify when depth is sufficient.

Typically triggered on login via scripts/login_ingest.sh (--if-due skips if
already ran successfully today).
"""

from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hireability.config import HISTORY_DAYS, MIN_SCRAPED_DAYS
from hireability.cron.notify import log_run, send_notification
from hireability.cron.sufficiency import (
    already_ran_today,
    check_sufficiency,
    load_cron_state,
    record_run,
)
from hireability.market.daily import market_daily_stats, rebuild_market_daily
from hireability.scrapers.jobs import fetch_jobs_by_source
from hireability.scrapers.layoffs import fetch_layoffs
from hireability.storage import init_db, save_jobs, save_layoffs


def run_ingest(*, history_days: int, dry_run: bool) -> dict[str, int]:
    init_db()
    summary = {"layoffs_fetched": 0, "layoffs_inserted": 0, "jobs_inserted": 0}

    if dry_run:
        return summary

    layoffs = fetch_layoffs(include_seed=True)
    summary["layoffs_fetched"] = len(layoffs)
    summary["layoffs_inserted"] = save_layoffs(layoffs)

    grouped = fetch_jobs_by_source()
    for source_posts in grouped.values():
        summary["jobs_inserted"] += save_jobs(source_posts)

    rebuild_market_daily(history_days=history_days)
    return summary


def _format_checks(report) -> str:
    lines = []
    for name, ok in report.checks.items():
        lines.append(f"  {'✓' if ok else '✗'} {name}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Daily hireability data ingest + sufficiency alerts")
    parser.add_argument("--dry-run", action="store_true", help="Check sufficiency without ingesting")
    parser.add_argument("--history-days", type=int, default=HISTORY_DAYS)
    parser.add_argument("--notify-always", action="store_true", help="Notify every run, not only milestones/failures")
    parser.add_argument(
        "--if-due",
        action="store_true",
        help="Skip if a successful ingest already ran today (for login autostart)",
    )
    args = parser.parse_args()

    state = load_cron_state()
    ok = True

    if args.if_due and not args.dry_run and already_ran_today(state):
        log_run("Ingest skipped — already ran successfully today.", level="info")
        return 0

    try:
        if args.dry_run:
            ingest_summary = {"dry_run": True}
        else:
            ingest_summary = run_ingest(history_days=args.history_days, dry_run=False)

        report = check_sufficiency(state)
        state = record_run(ok=True, report=report, state=state)
        market = market_daily_stats()

        status_lines = [
            report.message,
            _format_checks(report),
            f"Jobs inserted today: {ingest_summary.get('jobs_inserted', 0)}",
            f"Timeline: {market.get('min_date')} → {market.get('max_date')} "
            f"({market.get('scraped_days', 0)}/{MIN_SCRAPED_DAYS} live scrape days)",
        ]
        body = "\n".join(status_lines)

        if report.newly_sufficient:
            send_notification("Hireability — data sufficient", body, level="success")
        elif args.notify_always:
            send_notification("Hireability — daily ingest", body, level="info")
        else:
            log_run(body, level="info")
            if not report.sufficient and int(state.get("run_count", 0)) % 7 == 0:
                send_notification("Hireability — weekly progress", body, level="info")

        return 0

    except Exception as exc:
        ok = False
        tb = traceback.format_exc()
        report = check_sufficiency(state)
        record_run(ok=False, report=report, state=state)
        send_notification(
            "Hireability — ingest failed",
            f"{exc}\n\nRun manually: python main.py ingest all",
            level="error",
        )
        print(tb, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
