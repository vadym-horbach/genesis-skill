"""Synthetic scenarios from the plan (Phase 2): signs, evidence levels and rule ids."""

from __future__ import annotations

from interest_signals.analysis.evidence import EvidenceContext, assess
from interest_signals.analysis.metrics import compute_pair_metrics
from interest_signals.analysis.ranking import compare, label_for
from tests.synthetic import gen


def run(views, project=None, status=None, ctx=None):
    s = gen.series(views, project=project, status=status)
    m = compute_pair_metrics(s)
    ev = assess(m, ctx)
    comp = compare([m], [ev], None)
    return m, ev, label_for(m, ev.level, comp)


def rule_ids(ev):
    return {r.rule_id for r in ev.reasons}


def test_stable_growth_is_high_evidence_candidate():
    m, ev, (label, rule) = run(gen.growth(annual=0.3))
    assert 0.2 < m.trend_normalized.annual_change < 0.4
    assert 0.2 < m.yoy_normalized < 0.45
    assert m.positive_window_share == 1.0
    assert m.spikes == []
    assert ev.level == "high", ev.reasons
    assert (label, rule) == ("candidate for further validation", "R2")


def test_flat_is_weaker_signal_not_low():
    m, ev, (label, _) = run(gen.flat())
    assert abs(m.trend_normalized.annual_change) < 0.05
    assert abs(m.yoy_normalized) < 0.08
    assert ev.level in ("medium", "high")
    assert label == "weaker signal"


def test_decline():
    m, ev, (label, _) = run(gen.decline())
    assert m.trend_normalized.annual_change < -0.2
    assert m.yoy_normalized < -0.2
    assert m.positive_window_share == 0.0
    assert ev.level == "high"
    assert label == "weaker signal"


def test_one_huge_spike_detected_and_dominates():
    values = gen.flat(base=100)
    values[12] *= 40
    m, ev, _ = run(values)
    assert m.spikes == [gen.MONTHS_24[12]]
    assert m.top_2_month_share > 0.4
    assert "L4_spike_dominated" in rule_ids(ev)
    assert ev.level == "low"


def test_high_volatility_is_measured():
    calm, _, _ = run(gen.flat())
    wild, ev, _ = run(gen.volatile())
    assert wild.volatility > 5 * calm.volatility
    assert ev.level in ("low", "medium")


def test_seasonality_yoy_near_zero_and_trend_ci_contains_zero():
    """YoY compares the same months, so seasonality cancels. Theil-Sen is not seasonality-proof
    (documented limitation); its CI must still include zero for a trendless seasonal series."""
    m, ev, _ = run(gen.seasonal())
    assert abs(m.yoy_normalized) < 0.1
    assert m.trend_normalized.ci_low < 0 < m.trend_normalized.ci_high
    assert ev.level != "high"


def test_missing_months_are_unavailable_not_zero():
    values = gen.growth()
    status = ["ok"] * 24
    for i in (3, 7, 9):
        status[i] = "unavailable"
    m, ev, _ = run(values, status=status)
    assert m.unavailable_months == 3
    assert m.months_available == 21
    assert "L2_unavailable_months" in rule_ids(ev)


def test_raw_growth_with_normalized_decline():
    views = gen.growth(annual=0.2, sigma=0.01)
    project = gen.growth(annual=0.6, base=1e8, sigma=0.0)
    m, _, (label, _) = run(views, project=project)
    assert m.yoy_raw > 0 and m.trend_raw.annual_change > 0
    assert m.yoy_normalized < 0 and m.trend_normalized.annual_change < 0
    assert label == "weaker signal"


def test_newly_created_page_short_history():
    values = gen.growth()
    status = ["not_existing"] * 14 + ["ok"] * 10
    m, ev, (label, _) = run(values, status=status)
    assert m.months_available == 10
    assert m.trend_normalized is None and m.yoy_normalized is None
    assert "L1_short_history" in rule_ids(ev)
    assert label == "insufficient evidence"


def test_zero_heavy_series_refuses_trend():
    values = gen.flat(base=5)
    status = ["zero_filled" if i % 3 == 0 else "ok" for i in range(24)]
    values = [0.0 if s == "zero_filled" else v for v, s in zip(values, status)]
    m, _, _ = run(values, status=status)
    assert m.trend_normalized is None
    assert "zero" in m.not_computed["trend_normalized"]


def test_lifecycle_warning_blocks_high():
    _, ev, _ = run(gen.growth(), ctx=EvidenceContext(lifecycle_warnings=1))
    assert ev.level == "medium"
    assert "H6_stable_page" in rule_ids(ev)
