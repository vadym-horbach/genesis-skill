"""Robust long-term trend (D25, D29) and rolling consistency (D30)."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.stats import theilslopes

from interest_signals import config
from interest_signals.models.result import TrendStat


@dataclass
class LogFit:
    stat: TrendStat
    intercept: float
    offset: float


def log_offset(values: list[float]) -> float:
    """0 when all values are positive; otherwise half the smallest positive value, so the log
    transform stays defined without dominating small series (unlike a fixed +1)."""
    if all(v > 0 for v in values):
        return 0.0
    positives = [v for v in values if v > 0]
    return min(positives) / 2 if positives else 1.0


def zero_share(values: list[float]) -> float:
    return sum(1 for v in values if v == 0) / len(values) if values else 1.0


def theil_sen_log(xs: list[int], ys: list[float]) -> LogFit | None:
    """Theil-Sen slope of log(y + offset) over month index; annualized as exp(12*slope) - 1."""
    if len(xs) < 3:
        return None
    offset = log_offset(ys)
    logs = np.log(np.asarray(ys, dtype=float) + offset)
    slope, intercept, low, high = theilslopes(logs, np.asarray(xs, dtype=float), alpha=0.95)
    stat = TrendStat(
        annual_change=math.expm1(12 * slope),
        ci_low=math.expm1(12 * low),
        ci_high=math.expm1(12 * high),
        slope_log=float(slope),
        intercept_log=float(intercept),
        points=len(xs),
        log_offset=offset,
    )
    return LogFit(stat=stat, intercept=float(intercept), offset=offset)


def trend(xs: list[int], ys: list[float]) -> tuple[LogFit | None, str | None]:
    """Trend with the documented refusals. Returns (fit, reason_if_not_computed)."""
    if len(xs) < config.MIN_MONTHS_FOR_GROWTH:
        return None, f"needs >= {config.MIN_MONTHS_FOR_GROWTH} months of data, has {len(xs)}"
    if zero_share(ys) > config.MAX_ZERO_SHARE:
        return None, f"more than {config.MAX_ZERO_SHARE:.0%} of months have zero views"
    fit = theil_sen_log(xs, ys)
    return (fit, None) if fit else (None, "not enough points")


def positive_window_share(xs: list[int], ys: list[float]) -> tuple[float | None, int]:
    """Share of rolling CONSISTENCY_WINDOW-month windows (step 1) with a positive Theil-Sen slope.

    12-month windows always contain one full seasonal cycle, so seasonality alone does not
    create falling windows."""
    if not xs:
        return None, 0
    points = dict(zip(xs, ys))
    first, last = min(xs), max(xs)
    width = config.CONSISTENCY_WINDOW
    positives = 0
    windows = 0
    for start in range(first, last - width + 2):
        wx = [x for x in range(start, start + width) if x in points]
        if len(wx) < config.MIN_POINTS_PER_WINDOW:
            continue
        wy = [points[x] for x in wx]
        offset = log_offset(wy)
        slope = theilslopes(np.log(np.asarray(wy) + offset), np.asarray(wx, dtype=float))[0]
        windows += 1
        positives += int(slope > 0)
    if windows < config.MIN_CONSISTENCY_WINDOWS:
        return None, windows
    return positives / windows, windows
