"""Checks that every number in agent-written report text comes from the result.

A number is grounded when it is a rounding, at its shown precision, of a value in the result
(raw, as a percentage, or in thousands/millions). Locale formats are accepted: `22 895`,
`22,895`, `22.895`, `6,1`, `−50 %`. Small integers (counts, months) and years are free.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from interest_signals import config
from interest_signals.models.result import AnalysisResult

NUMBER = re.compile(r"\d{1,3}(?:[   .,']\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?")
SCALES = (1.0, 1e3, 1e6)


def _readings(token: str) -> list[tuple[float, int]]:
    """Possible (value, decimals) readings of a number written in any common locale."""
    readings = [(float(re.sub(r"\D", "", token)), 0)]
    last = max(token.rfind("."), token.rfind(","))
    if last != -1:
        whole = re.sub(r"\D", "", token[:last])
        frac = token[last + 1:]
        if frac.isdigit():
            readings.append((float(f"{whole or 0}.{frac}"), len(frac)))
    return readings


def _is_free(value: float, decimals: int) -> bool:
    if decimals:
        return False
    return value <= config.REPORT_FREE_SMALL_NUMBER or 2000 <= value <= 2100


def result_numbers(result: AnalysisResult, texts: Iterable[str] = ()) -> list[float]:
    """Magnitudes the agent may quote: metrics (percentages as 0-100), scores, weights, period,
    and every number printed in the tool's own sentences (rationale, warnings)."""
    values: list[float] = [float(result.scope.period.months)]
    for m in result.metrics:
        values += [v for v in (m.recent_views, m.recent_per_million, m.spike_ratio) if v is not None]
        values += [v * 100 for v in (m.yoy_raw, m.yoy_normalized, m.positive_window_share,
                                     m.top_2_month_share) if v is not None]
        for t in (m.trend_raw, m.trend_normalized):
            if t:
                values += [t.annual_change * 100, t.ci_low * 100, t.ci_high * 100]
        values += [float(len(m.spikes)), float(m.months_available)]
    for s in result.series:
        values += [c.recent_share * 100 for c in s.components if c.recent_share is not None]
    if result.comparison.weighted:
        values += list(result.comparison.weighted.scores.values())
        values += list(result.comparison.weighted.weights.values())
    sentences = [s for r in result.rationale for s in r.sentences] + [w.message for w in result.warnings]
    for text in [*sentences, *texts]:
        for token in NUMBER.findall(text):
            values += [v for v, _ in _readings(token)]
    return [abs(v) for v in values]


def ungrounded(texts: Iterable[str], allowed: list[float]) -> list[str]:
    """Number tokens in `texts` that match no allowed value at their shown precision."""
    bad: list[str] = []
    for text in texts:
        for token in NUMBER.findall(text):
            if any(_is_free(v, d) for v, d in _readings(token)):
                continue
            if not any(
                abs(v - a / scale) <= 0.5 * 10 ** -d + 1e-9
                for v, d in _readings(token) for a in allowed for scale in SCALES if scale == 1 or a >= scale
            ):
                bad.append(token)
    return list(dict.fromkeys(bad))
