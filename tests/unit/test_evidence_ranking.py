from __future__ import annotations

import itertools

from interest_signals import config
from interest_signals.analysis.evidence import HIGH_RULES, LOW_RULES, EvidenceContext, assess
from interest_signals.analysis.ranking import compare, label_for, labels, rank_percentiles
from interest_signals.analysis.rationale import explain, fmt_int, fmt_num, fmt_pct
from interest_signals.models.result import PairEvidence, PairMetrics, TrendStat


def trend(annual: float) -> TrendStat:
    return TrendStat(annual_change=annual, ci_low=annual - 0.1, ci_high=annual + 0.1, slope_log=0.0,
                     intercept_log=0.0, points=24, log_offset=0.0)


def metrics(**kw) -> PairMetrics:
    base = dict(
        topic_id="t1", project="xx.wikipedia", months_available=24, zero_months=0,
        unavailable_months=0, recent_views=1000.0, recent_per_million=10.0, yoy_raw=0.2,
        yoy_normalized=0.2, trend_raw=trend(0.2), trend_normalized=trend(0.2),
        positive_window_share=0.9, windows=13, spikes=[], spike_ratio=1.2, top_2_month_share=0.1,
        volatility=0.05,
    )
    base.update(kw)
    return PairMetrics(**base)


def test_high_when_all_rules_hold():
    ev = assess(metrics())
    assert ev.level == "high" and ev.reasons == []


def test_each_low_rule_fires_alone():
    cases = {
        "L1_short_history": dict(months_available=12, yoy_normalized=None, trend_normalized=None),
        "L2_unavailable_months": dict(unavailable_months=3),
        "L3_yoy_trend_disagree": dict(yoy_normalized=0.3, trend_normalized=trend(-0.3)),
        "L4_spike_dominated": dict(top_2_month_share=0.5),
        "L6_growth_not_computed": dict(yoy_normalized=None),
    }
    for rule_id, kw in cases.items():
        ev = assess(metrics(**kw))
        assert ev.level == "low", rule_id
        assert rule_id in {r.rule_id for r in ev.reasons}, rule_id
    ev = assess(metrics(), EvidenceContext(low_confidence_resolution=True))
    assert [r.rule_id for r in ev.reasons] == ["L5_resolution_low_confidence"]
    assert len(LOW_RULES) == 6


def test_each_high_rule_blocks_alone():
    cases = {
        "H1_history_24m": dict(months_available=20),
        "H2_no_unavailable": dict(unavailable_months=1),
        "H3_signs_agree": dict(yoy_normalized=0.02, trend_normalized=trend(0.3)),
        "H4_consistent": dict(positive_window_share=0.5),
        "H5_few_spikes": dict(spikes=["2025-01", "2025-06"]),
    }
    for rule_id, kw in cases.items():
        ev = assess(metrics(**kw))
        assert ev.level == "medium", rule_id
        assert [r.rule_id for r in ev.reasons] == [rule_id]
    ev = assess(metrics(), EvidenceContext(lifecycle_warnings=2))
    assert [r.rule_id for r in ev.reasons] == ["H6_stable_page"]
    assert len(HIGH_RULES) == 6


def test_flat_yoy_does_not_count_as_disagreement():
    ev = assess(metrics(yoy_normalized=0.01, trend_normalized=trend(-0.4)))
    assert ev.level == "medium"


def test_rank_percentiles_with_ties():
    assert rank_percentiles({"a": 1, "b": 2, "c": 2, "d": 3}) == {"a": 0.0, "b": 0.5, "c": 0.5, "d": 1.0}
    assert rank_percentiles({"a": 5}) == {"a": 1.0}


def test_pareto_and_exclusions():
    ms = [
        metrics(topic_id="t1", project="a", recent_views=100, yoy_normalized=0.3),
        metrics(topic_id="t1", project="b", recent_views=50, yoy_normalized=0.1),
        metrics(topic_id="t2", project="a", recent_views=10, yoy_normalized=0.9),
        metrics(topic_id="t2", project="b", recent_per_million=None),
    ]
    evs = [assess(m) for m in ms]
    evs[1] = PairEvidence(topic_id="t1", project="b", level="medium", reasons=[])
    comp = compare(ms, evs, None)
    assert set(comp.pareto_front) == {"t1:a", "t2:a"}
    assert comp.dominated_by == {"t1:b": ["t1:a"]}
    assert "t2:b" in comp.excluded
    assert comp.weighted is None


def test_weighted_ranking_is_visible_and_ordered():
    ms = [metrics(project="a", recent_views=100, yoy_normalized=0.1),
          metrics(project="b", recent_views=10, yoy_normalized=0.5)]
    evs = [assess(m) for m in ms]
    comp = compare(ms, evs, {"growth": 3, "scale": 1})
    assert comp.weighted.order == ["t1:b", "t1:a"]
    assert comp.weighted.scores["t1:b"] == 0.75
    assert "preferences" in comp.weighted.note


def test_labels_cover_every_combination_exactly_once():
    values = [None, -0.3, 0.0, 0.3]
    for level, yoy, tr, share, front in itertools.product(
        ["low", "medium", "high"], values, values, [None, 0.2, 0.8], [True, False]
    ):
        m = metrics(yoy_normalized=yoy, trend_normalized=None if tr is None else trend(tr),
                    positive_window_share=share)
        comp = compare([m], [PairEvidence(topic_id="t1", project="xx.wikipedia", level=level, reasons=[])], None)
        if not front:
            comp.pareto_front = []
        name, rule = label_for(m, level, comp)
        assert rule in {"R1", "R2", "R3", "R4"}
        if level == "low" or yoy is None or tr is None:
            assert rule == "R1"
        if rule == "R2":
            assert yoy > config.FLAT_BAND and tr > config.FLAT_BAND and front


def test_rationale_numbers_match_result():
    m = metrics(recent_views=12345.4, recent_per_million=3.21, yoy_normalized=0.183)
    ev = assess(m)
    comp = compare([m], [ev], None)
    lb = labels([m], [ev], comp)[0]
    text = " ".join(explain("topic", m, ev, lb, comp).sentences)
    for number in (fmt_int(m.recent_views), fmt_num(m.recent_per_million), fmt_pct(m.yoy_normalized),
                   fmt_pct(m.trend_normalized.annual_change), fmt_pct(m.trend_normalized.ci_low)):
        assert number in text
    for banned in ("launch", "market size", "Launch"):
        assert banned not in text
