import calendar
from datetime import date

from hireability.models import LayoffEvent


def month_daily_layoff_rate(event: LayoffEvent) -> list[tuple[date, float]]:
    """Spread monthly macro layoff totals into uniform daily supply rates."""
    if event.source != "layoffs.fyi-chart":
        return [(event.event_date, float(event.headcount))]

    days_in_month = calendar.monthrange(event.event_date.year, event.event_date.month)[1]
    daily_rate = event.headcount / days_in_month
    return [
        (date(event.event_date.year, event.event_date.month, day), daily_rate)
        for day in range(1, days_in_month + 1)
    ]
