"""Historical demand seed from Indeed Hiring Lab (daily since 2020)."""

from __future__ import annotations

from datetime import date, timedelta
from io import StringIO

import pandas as pd
import requests

from hireability.config import INDEED_SOFTWARE_CSV, USER_AGENT

_SECTOR = "Software Development"
_VARIABLE = "total postings"


def fetch_indeed_software_demand(
    *,
    history_days: int = 730,
    end_date: date | None = None,
) -> pd.DataFrame:
    """
    Download Indeed Hiring Lab daily index for US Software Development postings.
    Returns columns: date, demand_index (100 = Feb 2020 baseline).
    """
    end_date = end_date or date.today()
    start_date = end_date - timedelta(days=history_days)

    response = requests.get(
        INDEED_SOFTWARE_CSV,
        headers={"User-Agent": USER_AGENT},
        timeout=60,
    )
    response.raise_for_status()

    frame = pd.read_csv(StringIO(response.text))
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    frame = frame[
        (frame["display_name"] == _SECTOR)
        & (frame["variable"] == _VARIABLE)
        & (frame["jobcountry"] == "US")
    ][["date", "indeed_job_postings_index"]].rename(
        columns={"indeed_job_postings_index": "demand_index"}
    )
    frame = frame[
        (frame["date"] >= start_date) & (frame["date"] <= end_date)
    ].sort_values("date")
    return frame.reset_index(drop=True)


def calibrate_demand_counts(
    demand_index: pd.DataFrame,
    scraped_daily: dict[date, float],
    *,
    calibration_days: int = 30,
) -> pd.DataFrame:
    """
    Map Indeed index values onto realistic daily posting counts using
    recent scraped job volumes as calibration anchors.
    """
    if demand_index.empty:
        return demand_index.assign(job_postings=0.0)

    frame = demand_index.copy()
    end_date = frame["date"].max()
    start_date = end_date - timedelta(days=calibration_days)
    recent = frame[frame["date"] >= start_date]

    scraped_total = sum(
        scraped_daily.get(row_date, 0.0)
        for row_date in recent["date"]
    )
    index_total = float(recent["demand_index"].sum())

    if scraped_total > 0 and index_total > 0:
        scale = scraped_total / index_total
    else:
        scale = 4.0

    frame["job_postings"] = frame["demand_index"] * scale

    for row_date, count in scraped_daily.items():
        if count > 0:
            frame.loc[frame["date"] == row_date, "job_postings"] = count

    return frame
