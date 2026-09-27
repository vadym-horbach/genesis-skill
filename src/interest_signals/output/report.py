"""One-page HTML report rendered from AnalysisResult with Jinja2 (D50), plus the view model shared
with the PDF. The agent's ReportContent adds the analysis and the report language."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from interest_signals.analysis.rationale import fmt_int, fmt_num, fmt_pct, fmt_share
from interest_signals.models.report import ReportContent
from interest_signals.models.result import AnalysisResult, pair_key
from interest_signals.output.texts import Texts

TEMPLATES = Path(__file__).resolve().parents[3] / "assets"
MAX_WARNINGS = 12
HIDDEN_WARNINGS = ("UA_CONTACT_MISSING",)


def report_warnings(result: AnalysisResult) -> list[str]:
    """English warning messages in report order (the list the agent translates)."""
    return [w.message for w in result.warnings if w.code.value not in HIDDEN_WARNINGS][:MAX_WARNINGS]


def report_details(result: AnalysisResult) -> dict[str, str]:
    return {pair_key(r.topic_id, r.project): " ".join(r.sentences) for r in result.rationale}


def view_model(result: AnalysisResult, content: ReportContent | None = None) -> dict[str, Any]:
    content = content or ReportContent()
    t = Texts(content)
    ev = {pair_key(e.topic_id, e.project): e for e in result.evidence}
    lb = {pair_key(x.topic_id, x.project): x for x in result.labels}
    topic_names = {tp.topic_id: content.topics.get(tp.topic_id, tp.query) for tp in result.scope.topics}
    english = content.is_english
    details = {**(report_details(result) if english else {}), **content.details}
    rows = []
    for m in result.metrics:
        key = pair_key(m.topic_id, m.project)
        score = result.comparison.weighted.scores.get(key) if result.comparison.weighted else None
        rows.append(
            {
                "key": key, "topic": topic_names[m.topic_id], "project": m.project,
                "scale": t.na(fmt_int(m.recent_views)), "relative": t.na(fmt_num(m.recent_per_million)),
                "yoy": t.na(fmt_pct(m.yoy_normalized)), "yoy_raw": t.na(fmt_pct(m.yoy_raw)),
                "trend": t.na(fmt_pct(m.trend_normalized.annual_change) if m.trend_normalized else "n/a"),
                "consistency": t.na(fmt_share(m.positive_window_share)),
                "spikes": len(m.spikes), "evidence": t.evidence(ev[key].level), "label": t.label(lb[key].label),
                "detail": details.get(key),
                "pareto": key in result.comparison.pareto_front,
                "score": t("not_available") if score is None else f"{score:.2f}",
            }
        )
    english_warnings = report_warnings(result)
    warnings = content.warnings if content.warnings and len(content.warnings) == len(english_warnings) \
        else english_warnings
    visible = [w for w in result.warnings if w.code.value not in HIDDEN_WARNINGS]
    limitations = content.limitations if content.limitations and len(content.limitations) == len(
        result.limitations) else result.limitations
    topics = [
        {
            "name": topic_names[tp.topic_id],
            "cluster": [f"{content.entities.get(e.key, e.label)} ({e.key})" for e in tp.cluster],
            "auto_selected": tp.auto_selected,
            "missing": [c.project for c in tp.coverage if c.status == "missing"],
        }
        for tp in result.scope.topics
    ]
    period = result.scope.period
    weighted = result.comparison.weighted
    return {
        "r": result, "t": t, "lang": content.language, "analysis": content.analysis, "rows": rows,
        "topics": topics, "warnings": warnings, "warnings_truncated": max(0, len(visible) - MAX_WARNINGS),
        "limitations": limitations, "has_details": any(r["detail"] for r in rows),
        "scope_period": t("scope_period", start=period.start, end=period.end, months=period.months,
                          languages=", ".join(result.scope.languages)),
        "score_note": t("score_note", weights=", ".join(f"{k}={v:g}" for k, v in weighted.weights.items()))
        if weighted else None,
        "footer": t("footer", run_id=result.run_id, hits=result.cache.hits, fetched=result.cache.fetched,
                    http=result.cache.http_requests, version=result.tool_version,
                    methodology=result.methodology_version),
        "series_names": {pair_key(s.topic_id, s.project): series_name(result, topic_names, s.topic_id, s.project)
                         for s in result.series},
    }


def series_name(result: AnalysisResult, topic_names: dict[str, str], topic_id: str, project: str) -> str:
    lang = project.split(".")[0]
    return lang if len(result.scope.topics) == 1 else f"{topic_names[topic_id]} ({lang})"


def _data_uri(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode()


def render_html(vm: dict[str, Any], charts: dict[str, bytes], out: Path) -> Path:
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html", "j2"]))
    template = env.get_template("report.html.j2")
    out.write_text(template.render(**vm, charts={k: _data_uri(v) for k, v in charts.items()}), encoding="utf-8")
    return out
