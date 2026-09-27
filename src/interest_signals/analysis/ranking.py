"""Comparison of (topic, project) pairs (D35-D37).

Default: Pareto front, no weighted score. A weighted score exists only when the user gives
weights; it is labeled as a result of those preferences.
"""

from __future__ import annotations

from interest_signals import config
from interest_signals.models.result import (
    Comparison,
    PairEvidence,
    PairLabel,
    PairMetrics,
    WeightedRanking,
    pair_key,
)


def axis_value(m: PairMetrics, field: str) -> float | None:
    return getattr(m, field)


def dominates(a: dict[str, float], b: dict[str, float]) -> bool:
    return all(a[k] >= b[k] for k in a) and any(a[k] > b[k] for k in a)


def rank_percentiles(values: dict[str, float]) -> dict[str, float]:
    """0 = worst, 1 = best; ties share their average rank."""
    n = len(values)
    if n == 1:
        return {k: 1.0 for k in values}
    ordered = sorted(values.items(), key=lambda kv: kv[1])
    out: dict[str, float] = {}
    i = 0
    while i < n:
        j = i
        while j + 1 < n and ordered[j + 1][1] == ordered[i][1]:
            j += 1
        avg_rank = (i + j) / 2
        for k in range(i, j + 1):
            out[ordered[k][0]] = avg_rank / (n - 1)
        i = j + 1
    return out


def compare(
    metrics: list[PairMetrics], evidence: list[PairEvidence], weights: dict[str, float] | None
) -> Comparison:
    level = {pair_key(e.topic_id, e.project): e.level for e in evidence}
    comparison = Comparison(axes=dict(config.AXES), candidates=[])
    vectors: dict[str, dict[str, float]] = {}
    for m in metrics:
        key = pair_key(m.topic_id, m.project)
        comparison.candidates.append(key)
        if level.get(key) == "low":
            comparison.excluded[key] = "evidence low"
            continue
        values = {axis: axis_value(m, field) for axis, field in config.AXES.items()}
        missing = [axis for axis, v in values.items() if v is None]
        if missing:
            comparison.excluded[key] = f"missing {', '.join(missing)}"
            continue
        vectors[key] = values  # type: ignore[assignment]
    for key, vec in vectors.items():
        by = [other for other, ov in vectors.items() if other != key and dominates(ov, vec)]
        if by:
            comparison.dominated_by[key] = by
        else:
            comparison.pareto_front.append(key)
    if weights and vectors:
        active = {axis: w for axis, w in weights.items() if w > 0}
        percentiles = {
            axis: rank_percentiles({k: v[axis] for k, v in vectors.items()}) for axis in active
        }
        total = sum(active.values())
        scores = {
            key: round(sum(w * percentiles[axis][key] for axis, w in active.items()) / total, 4)
            for key in vectors
        }
        comparison.weighted = WeightedRanking(
            weights=dict(weights),
            percentiles={k: {axis: round(percentiles[axis][k], 4) for axis in active} for k in vectors},
            scores=scores,
            order=sorted(scores, key=lambda k: -scores[k]),
        )
    return comparison


def label_for(m: PairMetrics, level: str, comparison: Comparison) -> tuple[str, str]:
    """Ordered rule table; the first matching rule wins and R4 is the fallback."""
    key = pair_key(m.topic_id, m.project)
    yoy = m.yoy_normalized
    trend = m.trend_normalized.annual_change if m.trend_normalized else None
    if level == "low" or yoy is None or trend is None:
        return "insufficient evidence", "R1"
    consistent = m.positive_window_share is not None and m.positive_window_share >= config.LABEL_MIN_CONSISTENCY
    rising_yoy, rising_trend = yoy > config.FLAT_BAND, trend > config.FLAT_BAND
    if key in comparison.pareto_front and rising_yoy and rising_trend and consistent:
        return "candidate for further validation", "R2"
    if rising_yoy or rising_trend:
        return "monitor", "R3"
    return "weaker signal", "R4"


def labels(metrics: list[PairMetrics], evidence: list[PairEvidence], comparison: Comparison) -> list[PairLabel]:
    level = {pair_key(e.topic_id, e.project): e.level for e in evidence}
    out: list[PairLabel] = []
    for m in metrics:
        name, rule = label_for(m, level[pair_key(m.topic_id, m.project)], comparison)
        out.append(PairLabel(topic_id=m.topic_id, project=m.project, label=name, rule_id=rule))  # type: ignore[arg-type]
    return out
