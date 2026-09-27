"""Render every artifact from one AnalysisResult. Output never recomputes metrics."""

from __future__ import annotations

from pathlib import Path

from interest_signals.models.result import AnalysisResult
from interest_signals.output.charts import save_charts
from interest_signals.output.pdf import render_pdf
from interest_signals.output.report import render_html


def render_all(result: AnalysisResult, run_dir: Path, formats: list[str]) -> dict[str, str]:
    artifacts = {"analysis": str(run_dir / "analysis.json"), "request": str(run_dir / "request.json")}
    charts = save_charts(result, run_dir / "charts")
    artifacts.update({f"chart_{k}": v for k, v in charts.items()})
    if "html" in formats:
        artifacts["report_html"] = str(render_html(result, charts, run_dir / "report.html"))
    if "pdf" in formats:
        artifacts["report_pdf"] = str(render_pdf(result, run_dir / "report.pdf"))
    return artifacts
