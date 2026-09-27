"""One-page A4 PDF built with matplotlib only (D5): no extra dependency, no native libraries."""

from __future__ import annotations

import math
import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402

from interest_signals.models.result import AnalysisResult  # noqa: E402
from interest_signals.output.charts import draw_normalized, draw_raw  # noqa: E402
from interest_signals.output.report import view_model  # noqa: E402

A4 = (8.27, 11.69)
MAX_TABLE_ROWS = 12
MAX_RATIONALE_ROWS = 4
MAX_PDF_WARNINGS = 6


def _wrap(text: str, width: int = 120) -> str:
    return "\n".join(textwrap.wrap(text, width))


def render_pdf(result: AnalysisResult, out: Path) -> Path:
    vm = view_model(result)
    n_rows = min(len(vm["rows"]), MAX_TABLE_ROWS)
    n_series = len(result.series)
    raw_rows = math.ceil(n_series / 3) if n_series else 1
    rationale_rows = MAX_RATIONALE_ROWS if n_rows <= 4 else 2
    fig = plt.figure(figsize=A4)
    grid = fig.add_gridspec(
        6, 1,
        height_ratios=[0.7, 0.25 + 0.17 * (n_rows + 1), 0.35 + 0.42 * rationale_rows, 2.0,
                       0.55 + 0.5 * raw_rows, 1.25],
        hspace=0.35, left=0.06, right=0.97, top=0.97, bottom=0.02,
    )

    period = result.scope.period
    def describe(t) -> str:
        labels = ", ".join(e.label for e in t.cluster)
        text = labels if labels.casefold() == t.query.casefold() else f"{t.query}: {labels}"
        return text + (" (auto-selected)" if t.auto_selected else "")

    topics = "; ".join(describe(t) for t in result.scope.topics)
    head = fig.add_subplot(grid[0])
    head.axis("off")
    head.text(0, 1, "Interest signals: Wikipedia attention by language", fontsize=13, weight="bold", va="top")
    head.text(
        0, 0.62,
        _wrap(f"Period {period.start} to {period.end} ({period.months} complete months). Languages: "
              f"{', '.join(result.scope.languages)}. Articles: {topics}.", 125)
        + "\n" + "Traffic: human users (agent=user), all access, monthly. Source: Wikimedia Analytics API.",
        fontsize=7, va="top",
    )

    table_ax = fig.add_subplot(grid[1])
    table_ax.axis("off")
    rows = vm["rows"][:MAX_TABLE_ROWS]
    weighted = result.comparison.weighted
    cells = []
    for r in rows:
        cell = [r["topic"][:24], r["project"], r["scale"], r["relative"], r["yoy"], r["trend"],
                r["consistency"], r["evidence"], r["label"]]
        if weighted:
            cell.append("n/a" if r["score"] is None else f"{r['score']:.2f}")
        cells.append(cell)
    headers = ["Topic", "Edition", "Views/mo", "Per 1M", "YoY (norm.)", "Trend/yr", "Rising win.",
               "Evidence", "Label"] + (["Score*"] if weighted else [])
    if cells:
        table = table_ax.table(cellText=cells, colLabels=headers, cellLoc="left", bbox=[0, 0, 1, 1])
        table.auto_set_font_size(False)
        table.set_fontsize(6)
        widths = [0.15, 0.11, 0.08, 0.06, 0.08, 0.07, 0.07, 0.07, 0.19] + ([0.06] if weighted else [])
        total = sum(widths)
        for (_row, col), cell in table.get_celld().items():
            cell.set_width(widths[col] / total)
            cell.set_linewidth(0.3)

    rat_ax = fig.add_subplot(grid[2])
    rat_ax.axis("off")
    lines = []
    for r in vm["rows"][:rationale_rows]:
        lines.append(_wrap(" ".join(r["rationale"]), 165))
    if len(vm["rows"]) > rationale_rows:
        lines.append(f"... {len(vm['rows']) - rationale_rows} more explanations in report.html / analysis.json")
    rat_ax.text(0, 1, "Why (generated from the data)\n" + "\n".join(lines), fontsize=5.8, va="top")
    if weighted:
        rat_ax.text(0, 0, f"* Score from your weights {weighted.weights} over rank percentiles; "
                    "it reflects your preferences, not an objective truth.", fontsize=5.5, va="bottom")

    draw_normalized(fig.add_subplot(grid[3]), result)
    draw_raw(fig, grid[4], result)

    foot = fig.add_subplot(grid[5])
    foot.axis("off")
    warnings = [f"[{w.code.value}] {w.message}" for w in vm["warnings"][:MAX_PDF_WARNINGS]]
    hidden = len(result.warnings) - len(warnings)
    if hidden > 0:
        warnings.append(f"... {hidden} more warnings: see analysis.json")
    text = "Warnings\n" + ("\n".join(_wrap(w, 150) for w in warnings) or "none")
    text += "\n\nLimitations\n" + "\n".join(_wrap("- " + x, 150) for x in result.limitations[:3])
    text += (f"\n\nRun {result.run_id} | cache: {result.cache.hits} hits, {result.cache.fetched} fetched, "
             f"{result.cache.http_requests} HTTP requests | tool {result.tool_version}")
    foot.text(0, 1, text, fontsize=5.6, va="top")

    with PdfPages(out) as pdf:
        pdf.savefig(fig)
    plt.close(fig)
    return out
