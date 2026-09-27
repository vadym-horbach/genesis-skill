"""Render a report from one AnalysisResult and the agent's ReportContent. Output never
recomputes metrics. Reports are written only on request, into the user's directory."""

from __future__ import annotations

import re
from pathlib import Path

from interest_signals.models.errors import Code, FatalError, Issue, error, warning
from interest_signals.models.report import ReportContent
from interest_signals.models.result import AnalysisResult
from interest_signals.output import grounding
from interest_signals.output.charts import chart_images
from interest_signals.output.pdf import render_pdf
from interest_signals.output.report import render_html, report_details, report_warnings, view_model
from interest_signals.output.texts import ENGLISH, Texts


def report_template(result: AnalysisResult) -> dict:
    """Skeleton of ReportContent prefilled with English, for the agent to fill and translate."""
    return {
        "language": "en",
        "analysis": {"headline": "", "findings": [""], "recommendation": "", "next_steps": []},
        "text": dict(ENGLISH),
        "topics": {t.topic_id: t.query for t in result.scope.topics},
        "entities": {e.key: e.label for t in result.scope.topics for e in t.cluster},
        "details": report_details(result),
        "warnings": report_warnings(result),
        "limitations": list(result.limitations),
    }


def check_content(result: AnalysisResult, content: ReportContent) -> list[Issue]:
    """Reject numbers not found in the result; warn about untranslated parts."""
    written = list(content.details.values())
    if content.analysis:
        a = content.analysis
        written += [a.headline, *a.findings, a.recommendation, *a.next_steps]
    allowed = grounding.result_numbers(result, report_details(result).values())
    bad = grounding.ungrounded(written, allowed)
    if bad:
        raise FatalError(
            error(
                Code.REPORT_CONTENT_INVALID,
                f"Report text contains numbers that are not in the analysis result: {', '.join(bad)}.",
                "Use only numbers from the envelope summary (rationale, metrics, warnings), rounded "
                "at most to thousands or millions. Remove or replace these numbers and render again.",
                numbers=bad,
            )
        )
    issues: list[Issue] = []
    if not content.is_english:
        missing = Texts(content).missing_keys()
        if content.warnings is None and report_warnings(result):
            missing.append("warnings")
        if content.limitations is None:
            missing.append("limitations")
        if missing:
            issues.append(warning(
                Code.REPORT_UNTRANSLATED,
                f"Report language is '{content.language}', but {len(missing)} entries are not translated "
                f"(shown in English or omitted): {', '.join(missing[:8])}{' ...' if len(missing) > 8 else ''}.",
                "Translate every entry of `report-template` output and render again.",
            ))
    return issues


def _pdf_missing_glyphs(vm: dict) -> set[str]:
    from matplotlib import font_manager
    from matplotlib.ft2font import FT2Font

    charmap = FT2Font(font_manager.findfont("DejaVu Sans")).get_charmap()
    content: ReportContent = vm["t"].content
    texts = [*vm["t"].values.values(), *content.topics.values(), *content.entities.values(),
             *(content.warnings or []), *(content.limitations or [])]
    if content.analysis:
        a = content.analysis
        texts += [a.headline, *a.findings, a.recommendation, *a.next_steps]
    return {c for text in texts for c in text if not c.isspace() and ord(c) not in charmap}


def report_basename(result: AnalysisResult) -> str:
    slug = "-".join(re.sub(r"[^\w]+", "-", t.query.casefold()).strip("-") for t in result.scope.topics)
    return f"interest-signals-{slug[:60].strip('-') or 'report'}-{result.run_id[-6:]}"


def render_report(
    result: AnalysisResult, content: ReportContent | None, out_dir: Path, formats: list[str]
) -> tuple[dict[str, str], list[Issue]]:
    issues = check_content(result, content) if content else []
    vm = view_model(result, content)
    out_dir.mkdir(parents=True, exist_ok=True)
    base = out_dir / report_basename(result)
    artifacts: dict[str, str] = {}
    if "html" in formats:
        charts = chart_images(result, vm["series_names"], vm["t"])
        artifacts["report_html"] = str(render_html(vm, charts, base.with_suffix(".html")))
    if "pdf" in formats:
        missing = _pdf_missing_glyphs(vm)
        if missing:
            issues.append(warning(
                Code.REPORT_PDF_GLYPHS_MISSING,
                f"The PDF font has no glyphs for {len(missing)} characters of this language; they show "
                "as boxes in the PDF.",
                "Give the user the HTML report instead (it uses the browser's fonts).",
            ))
        artifacts["report_pdf"] = str(render_pdf(vm, base.with_suffix(".pdf")))
    return artifacts, issues
