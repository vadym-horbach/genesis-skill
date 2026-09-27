"""Calendar-month helpers. Analysis periods use complete calendar months only (D23)."""

from __future__ import annotations

import os
from datetime import date

from interest_signals import config
from interest_signals.models.result import Period


def today() -> date:
    override = os.environ.get("INTEREST_SIGNALS_TODAY")
    return date.fromisoformat(override) if override else date.today()


def month_index(month: str) -> int:
    return int(month[:4]) * 12 + int(month[5:7]) - 1


def month_from_index(index: int) -> str:
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def add_months(month: str, delta: int) -> str:
    return month_from_index(month_index(month) + delta)


def last_complete_month(on: date | None = None) -> str:
    on = on or today()
    return add_months(f"{on.year:04d}-{on.month:02d}", -1)


def month_range(start: str, end: str) -> list[str]:
    return [month_from_index(i) for i in range(month_index(start), month_index(end) + 1)]


def resolve_period(months: int, end_month: str | None = None) -> Period:
    """Last `months` complete months ending at `end_month` (default: last complete month)."""
    latest = last_complete_month()
    end = end_month or latest
    if month_index(end) > month_index(latest):
        end = latest
    start = add_months(end, -(months - 1))
    if month_index(start) < month_index(config.EARLIEST_MONTH):
        start = config.EARLIEST_MONTH
    return Period(start=start, end=end, months=month_index(end) - month_index(start) + 1)
