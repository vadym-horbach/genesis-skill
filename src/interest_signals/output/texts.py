"""Report interface text. English is the default; ReportContent.text overrides any key.

Placeholders in braces are filled by code and must be kept in translations.
"""

from __future__ import annotations

from typing import Any

from interest_signals.models.report import ReportContent

ENGLISH: dict[str, str] = {
    "title": "Interest signals: Wikipedia attention by language",
    "analysis": "Analysis",
    "findings": "Findings",
    "recommendation": "Recommendation",
    "next_steps": "Next steps",
    "scope": "What was analyzed",
    "scope_period": "Period {start} to {end} ({months} complete months). Language editions: {languages}.",
    "scope_traffic": "Traffic: human users (agent=user), all access, monthly. Source: Wikimedia Analytics API.",
    "auto_selected": "auto-selected; check it is the intended article",
    "no_article": "No article in: {projects}.",
    "comparison": "Comparison",
    "col_topic": "Topic",
    "col_edition": "Edition",
    "col_views": "Views/month",
    "col_per_million": "Per 1M views",
    "col_yoy": "YoY (normalized)",
    "col_yoy_raw": "YoY (raw)",
    "col_trend": "Trend/year",
    "col_rising": "Rising windows",
    "col_spikes": "Spikes",
    "col_evidence": "Evidence",
    "col_label": "Label",
    "col_score": "Score*",
    "pareto_note": "● not dominated on scale, relative attention, normalized growth and consistency (Pareto front).",
    "score_note": "* Score = your weights {weights} over rank percentiles; it reflects your preferences, "
    "not an objective truth.",
    "details": "Details by topic and edition",
    "charts": "Charts",
    "chart_relative": "Relative attention: views per 1M views of the language edition (dashed: trend, ▲ spike)",
    "chart_raw": "{series}: monthly views",
    "warnings": "Warnings",
    "none": "none",
    "more_warnings": "... {count} more in analysis.json",
    "limitations": "Limitations",
    "footer": "Run {run_id} · cache: {hits} hits, {fetched} fetched, {http} HTTP requests · "
    "interest-signals {version}, methodology {methodology}",
    "not_available": "n/a",
    "label_candidate for further validation": "candidate for further validation",
    "label_monitor": "monitor",
    "label_weaker signal": "weaker signal",
    "label_insufficient evidence": "insufficient evidence",
    "evidence_high": "high",
    "evidence_medium": "medium",
    "evidence_low": "low",
}


class Texts:
    """Interface text for one report: English merged with the agent's translations."""

    def __init__(self, content: ReportContent | None):
        self.content = content or ReportContent()
        self.values = {**ENGLISH, **{k: v for k, v in self.content.text.items() if k in ENGLISH}}

    def __call__(self, key: str, **fields: Any) -> str:
        text = self.values[key]
        if not fields:
            return text
        try:
            return text.format(**fields)
        except (KeyError, IndexError, ValueError):  # a translation broke a placeholder
            return ENGLISH[key].format(**fields)

    def missing_keys(self) -> list[str]:
        return [] if self.content.is_english else sorted(set(ENGLISH) - set(self.content.text))

    def label(self, value: str) -> str:
        return self.values.get(f"label_{value}", value)

    def evidence(self, value: str) -> str:
        return self.values.get(f"evidence_{value}", value)

    def na(self, value: str) -> str:
        return self.values["not_available"] if value == "n/a" else value
