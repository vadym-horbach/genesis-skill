"""Template explanations filled only with numbers from the result (D53).

The agent retells these sentences instead of composing its own numeric claims.
"""

from __future__ import annotations

from interest_signals import config
from interest_signals.models.result import (
    Comparison,
    PairEvidence,
    PairLabel,
    PairMetrics,
    PairRationale,
    pair_key,
)


def fmt_int(value: float | None) -> str:
    return "n/a" if value is None else f"{value:,.0f}"


def fmt_num(value: float | None, digits: int = 1) -> str:
    return "n/a" if value is None else f"{value:,.{digits}f}"


def fmt_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:+.0f}%"


def fmt_share(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.0f}%"


RULE_TEXT = {
    "R1": "evidence is too weak to rank",
    "R2": "not dominated on scale, relative attention, growth and consistency, with consistent growth",
    "R3": f"some growth above +{config.FLAT_BAND:.0%}, but dominated by another option or not consistent",
    "R4": f"no normalized growth beyond +-{config.FLAT_BAND:.0%}",
}


def explain(
    topic_label: str, m: PairMetrics, ev: PairEvidence, label: PairLabel, comparison: Comparison
) -> PairRationale:
    key = pair_key(m.topic_id, m.project)
    s1 = (
        f"{m.project}, '{topic_label}': about {fmt_int(m.recent_views)} views per month recently "
        f"({fmt_num(m.recent_per_million)} per 1M views of {m.project})."
    )
    if m.yoy_normalized is None and m.trend_normalized is None:
        why = m.not_computed.get("trend_normalized") or m.not_computed.get("yoy_normalized") or "n/a"
        s2 = f"Growth was not computed: {why}."
    else:
        t = m.trend_normalized
        trend_part = (
            f"long-term trend {fmt_pct(t.annual_change)} per year "
            f"(95% CI {fmt_pct(t.ci_low)} to {fmt_pct(t.ci_high)})"
            if t
            else "long-term trend not computed"
        )
        s2 = (
            f"Relative attention changed {fmt_pct(m.yoy_normalized)} year over year, {trend_part}; "
            f"{fmt_share(m.positive_window_share)} of 12-month windows were rising"
            f"{', with ' + str(len(m.spikes)) + ' spike month(s)' if m.spikes else ', no spikes'}."
        )
    reasons = "; ".join(r.description for r in ev.reasons) or "all evidence rules satisfied"
    position = ""
    if key in comparison.dominated_by:
        position = f" Dominated by {', '.join(comparison.dominated_by[key])}."
    elif key in comparison.pareto_front:
        position = " Not dominated by other compared options."
    s3 = f"Evidence {ev.level} ({reasons}). Label '{label.label}': {RULE_TEXT[label.rule_id]}.{position}"
    return PairRationale(topic_id=m.topic_id, project=m.project, sentences=[s1, s2, s3])
