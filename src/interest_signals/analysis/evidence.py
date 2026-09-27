"""Evidence quality: an explicit, testable rule table (D33). No percentage 'confidence'.

`low` if any LOW rule fires. Otherwise `high` if no HIGH rule is broken, else `medium`.
Statistical uncertainty of the trend is reported separately (trend CI), not mixed in here.
"""

from __future__ import annotations

from dataclasses import dataclass

from interest_signals import config
from interest_signals.models.result import EvidenceReason, PairEvidence, PairMetrics


@dataclass
class EvidenceContext:
    lifecycle_warnings: int = 0
    low_confidence_resolution: bool = False


def direction(value: float) -> int:
    """+1 rising, -1 falling, 0 flat (within +-FLAT_BAND)."""
    if value > config.FLAT_BAND:
        return 1
    if value < -config.FLAT_BAND:
        return -1
    return 0


def _directions(m: PairMetrics) -> tuple[int, int] | None:
    if m.yoy_normalized is None or m.trend_normalized is None:
        return None
    return direction(m.yoy_normalized), direction(m.trend_normalized.annual_change)


def _signs_disagree(m: PairMetrics) -> bool:
    d = _directions(m)
    return d is not None and d[0] * d[1] == -1


def _signs_agree(m: PairMetrics) -> bool:
    d = _directions(m)
    return d is not None and d[0] == d[1]


LOW_RULES = [
    ("L1_short_history", lambda m, c: m.months_available < config.MIN_MONTHS_FOR_GROWTH,
     f"fewer than {config.MIN_MONTHS_FOR_GROWTH} months of data"),
    ("L2_unavailable_months", lambda m, c: m.unavailable_months > config.EVIDENCE_LOW_MAX_UNAVAILABLE,
     f"more than {config.EVIDENCE_LOW_MAX_UNAVAILABLE} months unavailable"),
    ("L3_yoy_trend_disagree", lambda m, c: _signs_disagree(m),
     "year-over-year change and long-term trend point in opposite directions"),
    ("L4_spike_dominated",
     lambda m, c: m.top_2_month_share is not None and m.top_2_month_share > config.EVIDENCE_LOW_TOP2_SHARE,
     f"two months hold more than {config.EVIDENCE_LOW_TOP2_SHARE:.0%} of all views"),
    ("L5_resolution_low_confidence", lambda m, c: c.low_confidence_resolution,
     "topic resolution has low confidence"),
    ("L6_growth_not_computed",
     lambda m, c: m.months_available >= config.MIN_MONTHS_FOR_GROWTH
     and (m.yoy_normalized is None or m.trend_normalized is None),
     "normalized growth or trend could not be computed"),
]

HIGH_RULES = [
    ("H1_history_24m", lambda m, c: m.months_available >= config.EVIDENCE_HIGH_MIN_MONTHS,
     f"fewer than {config.EVIDENCE_HIGH_MIN_MONTHS} months of data"),
    ("H2_no_unavailable", lambda m, c: m.unavailable_months == 0, "some months unavailable"),
    ("H3_signs_agree", lambda m, c: _signs_agree(m), "growth and trend signs not confirmed equal"),
    ("H4_consistent",
     lambda m, c: m.positive_window_share is not None
     and (m.positive_window_share >= config.EVIDENCE_HIGH_MIN_CONSISTENCY
          or m.positive_window_share <= 1 - config.EVIDENCE_HIGH_MIN_CONSISTENCY),
     f"direction holds in less than {config.EVIDENCE_HIGH_MIN_CONSISTENCY:.0%} of rolling windows"),
    ("H5_few_spikes", lambda m, c: len(m.spikes) <= config.EVIDENCE_HIGH_MAX_SPIKES,
     f"more than {config.EVIDENCE_HIGH_MAX_SPIKES} spike month(s)"),
    ("H6_stable_page", lambda m, c: c.lifecycle_warnings == 0,
     "page lifecycle changes during the period"),
]


def assess(m: PairMetrics, ctx: EvidenceContext | None = None) -> PairEvidence:
    ctx = ctx or EvidenceContext()
    low = [
        EvidenceReason(rule_id=rid, effect="low", description=desc)
        for rid, rule, desc in LOW_RULES
        if rule(m, ctx)
    ]
    if low:
        return PairEvidence(topic_id=m.topic_id, project=m.project, level="low", reasons=low)
    blocked = [
        EvidenceReason(rule_id=rid, effect="blocks_high", description=desc)
        for rid, rule, desc in HIGH_RULES
        if not rule(m, ctx)
    ]
    level = "medium" if blocked else "high"
    return PairEvidence(topic_id=m.topic_id, project=m.project, level=level, reasons=blocked)
