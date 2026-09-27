"""Compact summary for the stdout envelope, so a cheap model does not need analysis.json."""

from __future__ import annotations

from typing import Any

from interest_signals.models.result import AnalysisResult, pair_key


def _round(value: float | None, digits: int = 3) -> float | None:
    return None if value is None else round(value, digits)


def result_summary(result: AnalysisResult, artifacts: dict[str, str]) -> dict[str, Any]:
    labels = {pair_key(lb.topic_id, lb.project): lb.label for lb in result.labels}
    evidence = {pair_key(e.topic_id, e.project): e.level for e in result.evidence}
    rationale = {pair_key(r.topic_id, r.project): r.sentences for r in result.rationale}
    rows = []
    for m in result.metrics:
        key = pair_key(m.topic_id, m.project)
        rows.append(
            {
                "key": key,
                "recent_views": _round(m.recent_views, 0),
                "per_million": _round(m.recent_per_million, 2),
                "yoy_normalized": _round(m.yoy_normalized),
                "trend_normalized_per_year": _round(m.trend_normalized.annual_change) if m.trend_normalized else None,
                "consistency": _round(m.positive_window_share, 2),
                "spikes": m.spikes,
                "evidence": evidence.get(key),
                "label": labels.get(key),
                "rationale": rationale.get(key, []),
            }
        )
    return {
        "run_id": result.run_id,
        "parent_run_id": result.parent_run_id,
        "period": result.scope.period.model_dump(by_alias=True),
        "languages": result.scope.languages,
        "topics": [
            {
                "topic_id": t.topic_id,
                "query": t.query,
                "auto_selected": t.auto_selected,
                "cluster": [f"{e.label} ({e.key})" for e in t.cluster],
            }
            for t in result.scope.topics
        ],
        "per_topic_language": rows,
        "pareto_front": result.comparison.pareto_front,
        "weighted_order": result.comparison.weighted.order if result.comparison.weighted else None,
        "cache": {"hits": result.cache.hits, "fetched": result.cache.fetched,
                  "http_requests": result.cache.http_requests},
        "artifacts": artifacts,
        "how_to_answer": "Retell `rationale` and the labels; do not invent numbers. Mention warnings "
        "and that pageviews are attention to articles, not demand or willingness to pay.",
    }
