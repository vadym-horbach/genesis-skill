"""Deterministic synthetic series (fixed seeds) for metric and evidence tests."""

from __future__ import annotations

import math

import numpy as np

from interest_signals.analysis.periods import month_range
from interest_signals.models.result import PairSeries

MONTHS_24 = month_range("2024-09", "2026-08")


def series(
    views: list[float | None],
    project: list[float] | None = None,
    status: list[str] | None = None,
    months: list[str] | None = None,
    topic_id: str = "t1",
    name: str = "xx.wikipedia",
) -> PairSeries:
    if months is None:
        months = MONTHS_24 if len(views) == 24 else month_range("2016-01", "2035-12")[: len(views)]
    project = project or [1e8] * len(views)
    if status is None:
        status = ["ok" if v is not None else "unavailable" for v in views]
    per_million = [v / p * 1e6 if v is not None and s in ("ok", "zero_filled") else None
                   for v, p, s in zip(views, project, status)]
    return PairSeries(
        topic_id=topic_id, project=name, months=months,
        views=[v if s in ("ok", "zero_filled") else None for v, s in zip(views, status)],
        project_views=project, per_million=per_million, status=status, components=[],
    )


def noise(n: int, sigma: float, seed: int) -> np.ndarray:
    return np.random.default_rng(seed).normal(0, sigma, n)


def growth(n=24, annual=0.3, base=1000.0, sigma=0.03, seed=1) -> list[float]:
    k = math.log1p(annual) / 12
    return [base * math.exp(k * i + e) for i, e in enumerate(noise(n, sigma, seed))]


def flat(n=24, base=1000.0, sigma=0.03, seed=2) -> list[float]:
    return growth(n, 0.0, base, sigma, seed)


def decline(n=24, annual=-0.3, base=1000.0, sigma=0.03, seed=3) -> list[float]:
    return growth(n, annual, base, sigma, seed)


def spike(n=24, base=1000.0, at=12, factor=20.0, seed=4) -> list[float]:
    values = flat(n, base, 0.03, seed)
    values[at] *= factor
    return values


def volatile(n=24, base=1000.0, seed=5) -> list[float]:
    return flat(n, base, 0.6, seed)


def seasonal(n=24, base=1000.0, amplitude=0.4, seed=6) -> list[float]:
    e = noise(n, 0.02, seed)
    return [base * math.exp(amplitude * math.sin(2 * math.pi * i / 12) + e[i]) for i in range(n)]
