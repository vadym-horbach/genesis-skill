"""One-page HTML report rendered from AnalysisResult with Jinja2 (D50)."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from interest_signals.analysis.rationale import fmt_int, fmt_num, fmt_pct, fmt_share
from interest_signals.models.result import AnalysisResult, pair_key

TEMPLATES = Path(__file__).resolve().parents[3] / "assets"
MAX_WARNINGS = 12


def view_model(result: AnalysisResult) -> dict[str, Any]:
    ev = {pair_key(e.topic_id, e.project): e for e in result.evidence}
    lb = {pair_key(x.topic_id, x.project): x for x in result.labels}
    ra = {pair_key(r.topic_id, r.project): r for r in result.rationale}
    topics = {t.topic_id: t.query for t in result.scope.topics}
    rows = []
    for m in result.metrics:
        key = pair_key(m.topic_id, m.project)
        rows.append(
            {
                "key": key, "topic": topics[m.topic_id], "project": m.project,
                "scale": fmt_int(m.recent_views), "relative": fmt_num(m.recent_per_million),
                "yoy": fmt_pct(m.yoy_normalized), "yoy_raw": fmt_pct(m.yoy_raw),
                "trend": fmt_pct(m.trend_normalized.annual_change) if m.trend_normalized else "n/a",
                "consistency": fmt_share(m.positive_window_share),
                "spikes": len(m.spikes), "evidence": ev[key].level, "label": lb[key].label,
                "rationale": ra[key].sentences,
                "pareto": key in result.comparison.pareto_front,
                "score": result.comparison.weighted.scores.get(key) if result.comparison.weighted else None,
            }
        )
    warnings = [w for w in result.warnings if w.code.value not in ("UA_CONTACT_MISSING",)]
    return {
        "r": result, "rows": rows, "warnings": warnings[:MAX_WARNINGS],
        "warnings_truncated": max(0, len(warnings) - MAX_WARNINGS),
    }


def _data_uri(path: str) -> str:
    return "data:image/png;base64," + base64.b64encode(Path(path).read_bytes()).decode()


def render_html(result: AnalysisResult, charts: dict[str, str], out: Path) -> Path:
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html", "j2"]))
    template = env.get_template("report.html.j2")
    html = template.render(**view_model(result), charts={k: _data_uri(v) for k, v in charts.items()})
    out.write_text(html)
    return out
