"""Persist and rebuild the daily market timeline used by 30/90-day scoring."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta

import pandas as pd

from hireability.config import DB_PATH, HISTORY_DAYS, MARKET_HISTORY_DAYS
from hireability.models import JobPost, LayoffEvent
from hireability.scrapers.demand_history import calibrate_demand_counts, fetch_indeed_software_demand
from hireability.market.supply import month_daily_layoff_rate
from hireability.storage import _connect, init_db, load_jobs, load_layoffs


def _layoffs_daily(
    layoffs: list[LayoffEvent],
    start_date: date,
    end_date: date,
) -> dict[date, float]:
    daily: dict[date, float] = defaultdict(float)
    for event in layoffs:
        for event_date, amount in month_daily_layoff_rate(event):
            if start_date <= event_date <= end_date:
                daily[event_date] += amount
    return daily


def _scraped_daily(
    jobs: list[JobPost],
    start_date: date,
    end_date: date,
) -> dict[date, float]:
    daily: dict[date, float] = defaultdict(float)
    for job in jobs:
        if start_date <= job.posted_date <= end_date:
            daily[job.posted_date] += 1.0
    return daily


def rebuild_market_daily(
    *,
    jobs: list[JobPost] | None = None,
    layoffs: list[LayoffEvent] | None = None,
    history_days: int = MARKET_HISTORY_DAYS,
    end_date: date | None = None,
    db_path=DB_PATH,
) -> int:
    """Merge Indeed demand history, layoff supply, and live scrapes into market_daily."""
    init_db(db_path)
    jobs = jobs if jobs is not None else load_jobs()
    layoffs = layoffs if layoffs is not None else load_layoffs()

    end_date = end_date or date.today()
    start_date = end_date - timedelta(days=history_days)

    indeed = fetch_indeed_software_demand(history_days=history_days, end_date=end_date)
    scraped = _scraped_daily(jobs, start_date, end_date)
    demand = calibrate_demand_counts(indeed, scraped)
    supply = _layoffs_daily(layoffs, start_date, end_date)

    ingested_at = datetime.utcnow().isoformat(timespec="seconds")
    demand_dates = set(demand["date"])
    rows = 0

    def _upsert_day(
        conn,
        row_date: date,
        job_postings: float,
        demand_index: float | None,
        scraped_count: float,
        source: str,
    ) -> None:
        conn.execute(
            """
            INSERT INTO market_daily
            (date, layoff_headcount, job_postings, demand_index, scraped_posts, source, ingested_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                layoff_headcount = excluded.layoff_headcount,
                job_postings = excluded.job_postings,
                demand_index = excluded.demand_index,
                scraped_posts = excluded.scraped_posts,
                source = excluded.source,
                ingested_at = excluded.ingested_at
            """,
            (
                row_date.isoformat(),
                supply.get(row_date, 0.0),
                job_postings,
                demand_index,
                scraped_count,
                source,
                ingested_at,
            ),
        )

    with _connect(db_path) as conn:
        for _, row in demand.iterrows():
            row_date = row["date"]
            scraped_count = scraped.get(row_date, 0.0)
            job_postings = scraped_count if scraped_count > 0 else float(row["job_postings"])
            _upsert_day(
                conn,
                row_date,
                job_postings,
                float(row["demand_index"]),
                scraped_count,
                "indeed+scrape" if scraped_count else "indeed",
            )
            rows += 1

        # Live scrapes newer than Indeed's lag (typically 1-2 weeks behind).
        for row_date, scraped_count in scraped.items():
            if row_date < start_date or row_date > end_date or scraped_count <= 0:
                continue
            if row_date in demand_dates:
                continue
            _upsert_day(
                conn,
                row_date,
                scraped_count,
                None,
                scraped_count,
                "scrape",
            )
            rows += 1

        # Layoff-only days with no demand row.
        for row_date, layoff_count in supply.items():
            if row_date < start_date or row_date > end_date:
                continue
            if row_date in demand_dates or scraped.get(row_date, 0.0) > 0:
                continue
            _upsert_day(conn, row_date, 0.0, None, 0.0, "layoffs")
            rows += 1

        conn.commit()

    return rows


def load_market_daily_frame(
    *,
    end_date: date | None = None,
    history_days: int = HISTORY_DAYS,
    db_path=DB_PATH,
) -> pd.DataFrame:
    init_db(db_path)
    end_date = end_date or date.today()
    start_date = end_date - timedelta(days=history_days)

    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT date, layoff_headcount, job_postings, demand_index, scraped_posts, source
            FROM market_daily
            WHERE date >= ? AND date <= ?
            ORDER BY date ASC
            """,
            (start_date.isoformat(), end_date.isoformat()),
        ).fetchall()

    if not rows:
        return pd.DataFrame()

    frame = pd.DataFrame(
        [
            {
                "date": date.fromisoformat(row["date"]),
                "layoffs": row["layoff_headcount"],
                "job_postings": row["job_postings"],
                "demand_index": row["demand_index"],
                "scraped_posts": row["scraped_posts"],
                "source": row["source"],
            }
            for row in rows
        ]
    )
    return frame


def market_daily_stats(db_path=DB_PATH) -> dict:
    init_db(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS total_days,
                MIN(date) AS min_date,
                MAX(date) AS max_date,
                SUM(CASE WHEN scraped_posts > 0 THEN 1 ELSE 0 END) AS scraped_days,
                SUM(CASE WHEN demand_index IS NOT NULL THEN 1 ELSE 0 END) AS seeded_days
            FROM market_daily
            """
        ).fetchone()

    if not row or row["total_days"] == 0:
        return {
            "total_days": 0,
            "min_date": None,
            "max_date": None,
            "scraped_days": 0,
            "seeded_days": 0,
        }

    return {
        "total_days": row["total_days"],
        "min_date": row["min_date"],
        "max_date": row["max_date"],
        "scraped_days": row["scraped_days"],
        "seeded_days": row["seeded_days"],
    }
