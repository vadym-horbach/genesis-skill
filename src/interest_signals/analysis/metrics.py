"""Per (topic, project) metrics computed from one aggregated series (D26-D32)."""

from __future__ import annotations

from statistics import median

from interest_signals import config
from interest_signals.analysis import anomalies, trends
from interest_signals.models.result import PairMetrics, PairSeries

VALID = ("ok", "zero_filled")


def points(series: PairSeries, values: list[float | None]) -> tuple[list[int], list[float]]:
    xs: list[int] = []
    ys: list[float] = []
    for i, (status, value) in enumerate(zip(series.status, values)):
        if status in VALID and value is not None:
            xs.append(i)
            ys.append(float(value))
    return xs, ys


def recent_median(series: PairSeries, values: list[float | None]) -> float | None:
    """Median of the last RECENT_MONTHS months of the period; None if any of them is invalid."""
    n = config.RECENT_MONTHS
    tail = list(zip(series.status[-n:], values[-n:]))
    if len(tail) < n or any(s not in VALID or v is None for s, v in tail):
        return None
    return float(median(v for _, v in tail))  # type: ignore[misc]


def yoy(series: PairSeries, values: list[float | None]) -> tuple[float | None, str | None]:
    """median(last 3 months) / median(same 3 months a year earlier) - 1."""
    n = config.RECENT_MONTHS
    if len(values) < 12 + n:
        return None, f"needs >= {12 + n} months"
    recent = recent_median(series, values)
    prior_idx = range(len(values) - 12 - n, len(values) - 12)
    prior = [values[i] for i in prior_idx if series.status[i] in VALID and values[i] is not None]
    if recent is None or len(prior) < n:
        return None, "missing months in the compared quarters"
    base = float(median(prior))  # type: ignore[arg-type]
    if base == 0:
        return None, "zero views a year earlier"
    return recent / base - 1, None


def compute_pair_metrics(series: PairSeries) -> PairMetrics:
    not_computed: dict[str, str] = {}
    xs_raw, ys_raw = points(series, series.views)
    xs_norm, ys_norm = points(series, series.per_million)
    m = PairMetrics(
        topic_id=series.topic_id,
        project=series.project,
        months_available=len(xs_raw),
        zero_months=sum(1 for s in series.status if s == "zero_filled"),
        unavailable_months=sum(1 for s in series.status if s == "unavailable"),
    )
    m.recent_views = recent_median(series, series.views)
    m.recent_per_million = recent_median(series, series.per_million)
    if m.recent_per_million is None:
        not_computed["recent_per_million"] = "project totals or recent months unavailable"

    enough = len(xs_raw) >= config.MIN_MONTHS_FOR_GROWTH
    if not enough:
        reason = f"needs >= {config.MIN_MONTHS_FOR_GROWTH} months of data, has {len(xs_raw)}"
        for name in ("yoy_raw", "yoy_normalized", "trend_raw", "trend_normalized", "consistency"):
            not_computed[name] = reason
    else:
        m.yoy_raw, why = yoy(series, series.views)
        if why:
            not_computed["yoy_raw"] = why
        m.yoy_normalized, why = yoy(series, series.per_million)
        if why:
            not_computed["yoy_normalized"] = why
        fit_raw, why = trends.trend(xs_raw, ys_raw)
        m.trend_raw = fit_raw.stat if fit_raw else None
        if why:
            not_computed["trend_raw"] = why
        fit_norm, why = trends.trend(xs_norm, ys_norm)
        m.trend_normalized = fit_norm.stat if fit_norm else None
        if why:
            not_computed["trend_normalized"] = why
        m.positive_window_share, m.windows = trends.positive_window_share(xs_norm, ys_norm)
        if m.positive_window_share is None:
            not_computed["consistency"] = (
                f"needs >= {config.MIN_CONSISTENCY_WINDOWS} rolling windows, has {m.windows}"
            )
        m.volatility = anomalies.volatility(xs_norm, ys_norm, fit_norm)

    m.spikes = [series.months[xs_raw[i]] for i in anomalies.spike_positions(ys_raw)]
    m.spike_ratio = anomalies.spike_ratio(ys_raw)
    m.top_2_month_share = anomalies.top_2_share(ys_raw)
    m.not_computed = not_computed
    return m
