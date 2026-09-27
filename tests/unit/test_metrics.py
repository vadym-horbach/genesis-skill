from __future__ import annotations

import math

import pytest

from interest_signals.analysis import anomalies, trends
from interest_signals.analysis.metrics import compute_pair_metrics, recent_median, yoy
from interest_signals.analysis.periods import (
    add_months,
    last_complete_month,
    month_range,
    resolve_period,
)
from tests.synthetic import gen


# -- periods ---------------------------------------------------------------------------------
def test_last_complete_month_crosses_year(monkeypatch):
    monkeypatch.setenv("INTEREST_SIGNALS_TODAY", "2026-01-15")
    assert last_complete_month() == "2025-12"


def test_resolve_period_24_complete_months(monkeypatch):
    monkeypatch.setenv("INTEREST_SIGNALS_TODAY", "2026-09-27")
    p = resolve_period(24)
    assert (p.start, p.end, p.months) == ("2024-09", "2026-08", 24)
    assert len(month_range(p.start, p.end)) == 24


def test_resolve_period_clamps_future_and_earliest(monkeypatch):
    monkeypatch.setenv("INTEREST_SIGNALS_TODAY", "2026-09-27")
    assert resolve_period(12, "2030-01").end == "2026-08"
    assert resolve_period(120, "2016-01").start == "2015-07"
    assert add_months("2025-11", 3) == "2026-02"


# -- scale, relative, YoY ---------------------------------------------------------------------
def test_recent_median_and_normalization():
    views = [100.0] * 21 + [300.0, 100.0, 200.0]
    s = gen.series(views, project=[2e6] * 24)
    assert recent_median(s, s.views) == 200.0
    assert recent_median(s, s.per_million) == pytest.approx(100.0)


def test_recent_median_none_when_last_month_unavailable():
    s = gen.series([100.0] * 24, status=["ok"] * 23 + ["unavailable"])
    assert recent_median(s, s.views) is None


def test_yoy_same_quarter_previous_year():
    views = [100.0] * 9 + [50.0, 50.0, 50.0] + [100.0] * 9 + [75.0, 75.0, 75.0]
    s = gen.series(views)
    value, why = yoy(s, s.views)
    assert why is None
    assert value == pytest.approx(0.5)


def test_yoy_zero_base_is_not_computed():
    views = [0.0] * 9 + [0.0] * 3 + [5.0] * 12
    s = gen.series(views, status=["zero_filled"] * 12 + ["ok"] * 12)
    value, why = yoy(s, s.views)
    assert value is None and "zero" in why


# -- trend ------------------------------------------------------------------------------------
def test_theil_sen_recovers_exponential_growth():
    ys = [1000 * math.exp(math.log(1.25) / 12 * i) for i in range(24)]
    fit = trends.theil_sen_log(list(range(24)), ys)
    assert fit.stat.annual_change == pytest.approx(0.25, rel=1e-6)
    assert fit.stat.ci_low <= fit.stat.annual_change <= fit.stat.ci_high
    assert fit.offset == 0.0


def test_log_offset_only_with_zeros():
    assert trends.log_offset([1.0, 2.0]) == 0.0
    assert trends.log_offset([0.0, 4.0, 2.0]) == 1.0


def test_trend_refuses_short_or_zero_heavy():
    assert trends.trend(list(range(10)), [1.0] * 10)[0] is None
    ys = [0.0 if i % 4 == 0 else 5.0 for i in range(24)]
    fit, why = trends.trend(list(range(24)), ys)
    assert fit is None and "zero" in why


def test_positive_window_share_counts_windows():
    ys = gen.growth(sigma=0.0)
    share, windows = trends.positive_window_share(list(range(24)), ys)
    assert windows == 13 and share == 1.0
    share, windows = trends.positive_window_share(list(range(14)), ys[:14])
    assert share is None and windows == 3


# -- anomalies --------------------------------------------------------------------------------
def test_spike_needs_size_and_robust_z():
    ys = [100.0] * 24
    ys[10] = 130.0
    assert anomalies.spike_positions(ys) == []
    ys[10] = 400.0
    assert anomalies.spike_positions(ys) == [10]


def test_top2_and_ratio():
    ys = [10.0] * 10
    ys[0] = 100.0
    assert anomalies.top_2_share(ys) == pytest.approx(110 / 190)
    assert anomalies.spike_ratio(ys) == 10.0


def test_volatility_zero_for_perfect_trend():
    ys = gen.growth(sigma=0.0)
    fit = trends.theil_sen_log(list(range(24)), ys)
    assert anomalies.volatility(list(range(24)), ys, fit) == pytest.approx(0.0, abs=1e-9)


def test_compute_pair_metrics_reports_reasons():
    m = compute_pair_metrics(gen.series(gen.growth()[:12]))
    assert m.yoy_normalized is None
    assert "15" in m.not_computed["trend_normalized"]
