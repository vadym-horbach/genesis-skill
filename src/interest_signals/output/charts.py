"""Two charts, drawn from AnalysisResult only (D49). No metric is recomputed here."""

from __future__ import annotations

import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.axes import Axes  # noqa: E402

from interest_signals.models.result import AnalysisResult, PairSeries  # noqa: E402

PALETTE = ["#2a6fdb", "#e0663a", "#2f9e6e", "#9b59b6", "#c9a227", "#d6457a", "#3fa7b5", "#7a7a7a"]


def _label(result: AnalysisResult, s: PairSeries) -> str:
    topics = {t.topic_id: t.query for t in result.scope.topics}
    lang = s.project.split(".")[0]
    return f"{lang}" if len(topics) == 1 else f"{topics[s.topic_id]} ({lang})"


def _x(s: PairSeries) -> list[int]:
    return list(range(len(s.months)))


def _ticks(ax: Axes, s: PairSeries, count: int = 6, fontsize: float = 7) -> None:
    step = max(1, len(s.months) // count)
    idx = list(range(0, len(s.months), step))
    ax.set_xticks(idx)
    ax.set_xticklabels([s.months[i] for i in idx], rotation=0, fontsize=fontsize)


def draw_normalized(ax: Axes, result: AnalysisResult) -> None:
    for i, s in enumerate(result.series):
        color = PALETTE[i % len(PALETTE)]
        ax.plot(_x(s), [v if v is not None else float("nan") for v in s.per_million],
                color=color, lw=1.6, label=_label(result, s))
        m = result.metric(s.topic_id, s.project)
        t = m.trend_normalized
        valid = [j for j, v in enumerate(s.per_million) if v is not None]
        if t and valid:
            ax.plot(valid, [math.exp(t.intercept_log + t.slope_log * j) - t.log_offset for j in valid],
                    color=color, lw=1, ls="--", alpha=0.8)
        for month in m.spikes:
            j = s.months.index(month)
            if s.per_million[j] is not None:
                ax.plot(j, s.per_million[j], marker="^", color=color, ms=6)
    ax.set_title("Relative attention: views per 1M views of the language edition (dashed: trend, ▲ spike)",
                 fontsize=8)
    ax.set_ylim(bottom=0)
    ax.grid(alpha=0.25)
    ax.legend(fontsize=7, loc="best", frameon=False)
    if result.series:
        _ticks(ax, result.series[0])


def draw_raw(fig, grid_spec, result: AnalysisResult) -> None:
    n = len(result.series)
    cols = min(3, max(1, n))
    rows = math.ceil(n / cols) if n else 1
    sub = grid_spec.subgridspec(rows, cols, hspace=0.9, wspace=0.35)
    for i, s in enumerate(result.series):
        ax = fig.add_subplot(sub[i // cols, i % cols])
        ax.bar(_x(s), [v or 0 for v in s.views], color=PALETTE[i % len(PALETTE)], width=0.8)
        ax.set_title(f"{_label(result, s)}: monthly views", fontsize=6.5, pad=2)
        ax.tick_params(labelsize=5.5)
        _ticks(ax, s, count=3, fontsize=5.5)
        ax.grid(alpha=0.2, axis="y")


def save_charts(result: AnalysisResult, charts_dir: Path) -> dict[str, str]:
    charts_dir.mkdir(parents=True, exist_ok=True)
    out: dict[str, str] = {}
    fig, ax = plt.subplots(figsize=(8, 3.6), dpi=130)
    draw_normalized(ax, result)
    fig.tight_layout()
    path = charts_dir / "relative_attention.png"
    fig.savefig(path)
    plt.close(fig)
    out["relative_attention"] = str(path)

    n = max(1, len(result.series))
    rows = math.ceil(n / min(3, n))
    fig = plt.figure(figsize=(8, 2.2 * rows), dpi=130)
    draw_raw(fig, fig.add_gridspec(1, 1)[0], result)
    path = charts_dir / "raw_views.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    out["raw_views"] = str(path)
    return out

