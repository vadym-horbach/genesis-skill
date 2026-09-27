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

A4 = (8.27, 11.69)
MAX_TABLE_ROWS = 12
MAX_PDF_WARNINGS = 6


def _wrap(text: str, width: int = 120) -> str:
    return "\n".join(textwrap.wrap(text, width))


def _analysis_lines(vm: dict) -> list[tuple[str, dict]]:
    """(text, style) lines of the agent's analysis block, wrapped for the page width."""
    a, t = vm["analysis"], vm["t"]
    lines: list[tuple[str, dict]] = []
    for part in textwrap.wrap(a.headline, 110):
        lines.append((part, {"fontsize": 8, "weight": "bold"}))
    sections = [(t("findings"), a.findings), (t("recommendation"), [a.recommendation])]
    if a.next_steps:
        sections.append((t("next_steps"), a.next_steps))
    for title, items in sections:
        lines.append((title, {"fontsize": 6.6, "weight": "bold"}))
        bullet = len(items) > 1 or title != t("recommendation")
        for item in items:
            wrapped = textwrap.wrap(item, 150)
            for j, part in enumerate(wrapped):
                prefix = ("• " if j == 0 else "  ") if bullet else ""
                lines.append((prefix + part, {"fontsize": 6.4}))
    return lines


def render_pdf(vm: dict, out: Path) -> Path:
    result: AnalysisResult = vm["r"]
    t = vm["t"]
    n_rows = min(len(vm["rows"]), MAX_TABLE_ROWS)
    n_series = len(result.series)
    raw_rows = math.ceil(n_series / 3) if n_series else 1
    analysis = _analysis_lines(vm) if vm["analysis"] else []
    fig = plt.figure(figsize=A4)
    grid = fig.add_gridspec(
        6, 1,
        height_ratios=[0.7, 0.1 + 0.125 * len(analysis), 0.3 + 0.17 * (n_rows + 1), 2.0,
                       0.55 + 0.5 * raw_rows, 1.25],
        hspace=0.35, left=0.06, right=0.97, top=0.97, bottom=0.02,
    )

    def describe(tp: dict) -> str:
        cluster = ", ".join(tp["cluster"])
        return f"{tp['name']}: {cluster}" + (f" ({t('auto_selected')})" if tp["auto_selected"] else "")

    head = fig.add_subplot(grid[0])
    head.axis("off")
    head.text(0, 1, t("title"), fontsize=13, weight="bold", va="top")
    head.text(0, 0.62, _wrap(f"{vm['scope_period']} " + "; ".join(describe(tp) for tp in vm["topics"]) + ".", 125)
              + "\n" + t("scope_traffic"), fontsize=7, va="top")

    an_ax = fig.add_subplot(grid[1])
    an_ax.axis("off")
    if analysis:
        step = 1 / len(analysis)
        for k, (text, style) in enumerate(analysis):
            an_ax.text(0, 1 - k * step, text, va="top", **style)

    table_ax = fig.add_subplot(grid[2])
    table_ax.axis("off")
    rows = vm["rows"][:MAX_TABLE_ROWS]
    weighted = result.comparison.weighted
    cells = []
    for r in rows:
        cell = [r["topic"][:24], r["project"], r["scale"], r["relative"], r["yoy"], r["trend"],
                r["consistency"], r["evidence"], r["label"]]
        if weighted:
            cell.append(r["score"])
        cells.append(cell)
    headers = [t(k) for k in ("col_topic", "col_edition", "col_views", "col_per_million", "col_yoy",
                              "col_trend", "col_rising", "col_evidence", "col_label")]
    headers += [t("col_score")] if weighted else []
    headers = ["\n".join(textwrap.wrap(h, 11)[:2]) for h in headers]  # translations run longer
    if cells:
        table = table_ax.table(cellText=cells, colLabels=headers, cellLoc="left", bbox=[0, 0.16, 1, 0.84])
        table.auto_set_font_size(False)
        table.set_fontsize(6)
        widths = [0.15, 0.11, 0.08, 0.06, 0.08, 0.07, 0.07, 0.07, 0.19] + ([0.06] if weighted else [])
        total = sum(widths)
        for (row, col), cell in table.get_celld().items():
            cell.set_width(widths[col] / total)
            cell.set_linewidth(0.3)
            if row == 0:
                cell.set_fontsize(5.3)
    note = t("pareto_note") + (f" {vm['score_note']}" if vm["score_note"] else "")
    table_ax.text(0, 0, _wrap(note, 170), fontsize=5.5, va="bottom")

    draw_normalized(fig.add_subplot(grid[3]), result, vm["series_names"], t)
    draw_raw(fig, grid[4], result, vm["series_names"], t)

    foot = fig.add_subplot(grid[5])
    foot.axis("off")
    warnings = vm["warnings"][:MAX_PDF_WARNINGS]
    hidden = len(vm["warnings"]) + vm["warnings_truncated"] - len(warnings)
    if hidden > 0:
        warnings = [*warnings, t("more_warnings", count=hidden)]
    text = t("warnings") + "\n" + ("\n".join(_wrap(w, 150) for w in warnings) or t("none"))
    text += "\n\n" + t("limitations") + "\n" + "\n".join(_wrap("- " + x, 150) for x in vm["limitations"][:3])
    text += "\n\n" + vm["footer"]
    foot.text(0, 1, text, fontsize=5.6, va="top")

    with PdfPages(out) as pdf:
        pdf.savefig(fig)
    plt.close(fig)
    return out
