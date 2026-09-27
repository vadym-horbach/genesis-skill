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


def report_template(result: AnalysisResult) -> dict[str, str]:
    """English values of every translatable entry, keyed as `--set KEY=VALUE` expects."""
    entries = {f"text.{k}": v for k, v in ENGLISH.items()}
    entries |= {f"topic.{t.topic_id}": t.query for t in result.scope.topics}
    entries |= {f"entity.{e.key}": e.label for t in result.scope.topics for e in t.cluster}
    entries |= {f"warning.{i}": w for i, w in enumerate(report_warnings(result), start=1)}
    entries |= {f"limitation.{i}": x for i, x in enumerate(result.limitations, start=1)}
    entries |= {f"detail.{k}": v for k, v in report_details(result).items()}
    return entries


def content_from_flags(language: str | None, headline: str | None, findings: list[str],
                       recommendation: str | None, next_steps: list[str], sets: list[str]) -> dict:
    """ReportContent fields from command-line flags (no JSON, so no braces on the command line)."""
    data: dict = {"language": language or "en", "text": {}, "topics": {}, "entities": {}, "details": {}}
    if headline or findings or recommendation or next_steps:
        data["analysis"] = {"headline": headline or "", "findings": findings,
                            "recommendation": recommendation or "", "next_steps": next_steps}
    lists: dict[str, dict[int, str]] = {"warnings": {}, "limitations": {}}
    targets = {"text": "text", "topic": "topics", "entity": "entities", "detail": "details"}
    for item in sets:
        key, sep, value = item.partition("=")
        kind, _, name = key.strip().partition(".")
        if not sep or not name:
            raise FatalError(error(Code.REPORT_CONTENT_INVALID, f"Bad --set '{item[:60]}'.",
                                   "Use --set KEY=VALUE with a KEY from report-template, e.g. --set text.title=..."))
        if kind in targets:
            data[targets[kind]][name] = value
        elif kind in ("warning", "limitation") and name.isdigit():
            lists[kind + "s"][int(name)] = value
        else:
            raise FatalError(error(Code.REPORT_CONTENT_INVALID, f"Unknown --set key '{key}'.",
                                   "Use a KEY printed by report-template."))
    for field, items in lists.items():
        if items:
            data[field] = [items[i] for i in sorted(items)]
    return data


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
        missing = [f"text.{k}" for k in Texts(content).missing_keys()]
        missing += [f"topic.{t.topic_id}" for t in result.scope.topics if t.topic_id not in content.topics]
        if content.warnings is None and report_warnings(result):
            missing.append("warning.*")
        if content.limitations is None:
            missing.append("limitation.*")
        if missing:
            issues.append(warning(
                Code.REPORT_UNTRANSLATED,
                f"Report language is '{content.language}', but {len(missing)} entries are not translated "
                f"(shown in English or omitted): {', '.join(missing[:8])}{' ...' if len(missing) > 8 else ''}.",
                "Add a --set KEY=... translation for each listed key (see report-template) and render again.",
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
