"""Command line entry point (run through scripts/analyze.py). Prints exactly one JSON envelope."""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from interest_signals import __version__
from interest_signals.cache.store import CacheStore, clear_cache, default_cache_dir
from interest_signals.models.envelope import Envelope
from interest_signals.models.errors import Code, FatalError, error
from interest_signals.models.report import ReportContent
from interest_signals.models.request import AnalysisRequest
from interest_signals.models.result import AnalysisResult
from interest_signals.output.render import report_template
from interest_signals.pipeline import runs
from interest_signals.pipeline.analyze import RunOptions, render_run, run_analysis
from interest_signals.providers.wikipedia.client import ApiError


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="analyze.py", description="Wikipedia interest signals by language.")
    p.add_argument("--version", action="store_true")
    p.add_argument("--request", help="Path to a request JSON file (preferred for agents).")
    p.add_argument("--topic", action="append", default=[], help="Topic text; repeat for more topics.")
    p.add_argument("--qids", action="append", default=[], help="Comma-separated Wikidata ids forming one topic.")
    p.add_argument("--languages", nargs="+", help="Wikipedia language codes, e.g. pl cs uk.")
    p.add_argument("--add-languages", nargs="+", help="Follow-up: add languages to the parent request.")
    p.add_argument("--add-topic", action="append", default=[], help="Follow-up: add a topic (text).")
    p.add_argument("--add-qids", action="append", default=[], help="Follow-up: add a topic from Wikidata ids.")
    p.add_argument("--months", type=int, help="Number of complete months (default 24).")
    p.add_argument("--end-month", help="Last month YYYY-MM (default: last complete month).")
    p.add_argument("--weights", help="Explicit preferences, e.g. growth=2,scale=1.")
    p.add_argument("--country", action="append", default=[], help="Countries (not supported; reported).")
    p.add_argument("--parent", help="Previous run id; its request is the base.")
    p.add_argument("--render", help="Write the report of an existing run (no recomputation).")
    p.add_argument("--content", help="With --render: ReportContent JSON file, or '-' for stdin.")
    p.add_argument("--content-json", help="With --render: ReportContent as one JSON argument.")
    p.add_argument("--format", nargs="+", action="extend", help="With --render: html, pdf or both (default).")
    p.add_argument("--out", help="With --render: report directory (default: current directory).")
    p.add_argument("--refresh", action="store_true", help="Ignore cached data and refetch.")
    p.add_argument("--no-cache", action="store_true", help="Do not read or write the cache.")
    return p


def parse_weights(text: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for part in text.split(","):
        if part.strip():
            name, _, value = part.partition("=")
            out[name.strip()] = float(value)
    return out


def qid_topic(text: str) -> dict[str, Any]:
    return {"qids": [q.strip() for q in text.split(",") if q.strip()]}


def request_from_args(args: argparse.Namespace, base: dict[str, Any] | None) -> dict[str, Any]:
    data: dict[str, Any] = dict(base or {})
    if args.request:
        data = json.loads(Path(args.request).read_text())
    topics = list(data.get("topics", []))
    if args.topic or args.qids:
        topics = [{"query": t} for t in args.topic] + [qid_topic(q) for q in args.qids]
    topics += [{"query": t} for t in args.add_topic] + [qid_topic(q) for q in args.add_qids]
    for i, t in enumerate(topics, start=1):
        t.setdefault("topic_id", f"t{i}")
    ids = [t["topic_id"] for t in topics]
    if len(ids) != len(set(ids)):
        for i, t in enumerate(topics, start=1):
            t["topic_id"] = f"t{i}"
    data["topics"] = topics
    if args.languages:
        data["languages"] = args.languages
    if args.add_languages:
        data["languages"] = list(dict.fromkeys([*data.get("languages", []), *args.add_languages]))
    if args.months:
        data["months"] = args.months
    if args.end_month:
        data["end_month"] = args.end_month
    if args.weights:
        data["criteria"] = {"weights": parse_weights(args.weights)}
    if args.country:
        data["countries"] = args.country
    return data


def cache_command(argv: list[str]) -> Envelope:
    action = argv[1] if len(argv) > 1 else "status"
    if action == "status":
        store = CacheStore()
        info = store.status()
        store.close()
        run_store = runs.RunStore()
        info["runs"] = run_store.count()
        run_store.close()
        return Envelope(status="ok", summary={"cache": info})
    if action == "clear":
        return Envelope(status="ok", summary={"cache": clear_cache()})
    raise FatalError(error(Code.INVALID_REQUEST, f"Unknown cache action '{action}'.", "Use `cache status` or `cache clear`."))


def template_command(argv: list[str]) -> Envelope:
    if len(argv) < 2:
        raise FatalError(error(Code.INVALID_REQUEST, "No run id given.", "Use `report-template <run_id>`."))
    store = runs.RunStore()
    result = AnalysisResult.model_validate_json(store.analysis_json(argv[1]))
    store.close()
    return Envelope(status="ok", summary={"run_id": result.run_id, "report_template": report_template(result)})


def read_content(ref: str | None, inline: str | None) -> ReportContent:
    if inline is not None:
        text = inline
    else:
        text = sys.stdin.read() if ref == "-" else Path(ref or "").read_text(encoding="utf-8")
    try:
        return ReportContent.model_validate_json(text)
    except ValidationError as exc:
        details = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()]
        hint = "; ".join(details) + ". In the single-quoted --content-json argument write apostrophes as ’."
        raise FatalError(error(Code.REPORT_CONTENT_INVALID, "Invalid report content.", hint)) from exc


def parse_formats(values: list[str] | None) -> list[str] | None:
    if not values:
        return None
    formats = list(dict.fromkeys(f.strip() for v in values for f in v.split(",") if f.strip()))
    unknown = set(formats) - {"html", "pdf"}
    if unknown:
        raise FatalError(error(Code.INVALID_REQUEST, f"Unknown formats {sorted(unknown)}.", "Use html, pdf or html,pdf."))
    return formats


def execute(argv: list[str]) -> Envelope:
    if argv and argv[0] == "cache":
        return cache_command(argv)
    if argv and argv[0] == "report-template":
        return template_command(argv)
    args = build_parser().parse_args(argv)
    if args.version:
        return Envelope(status="ok", summary={"version": __version__})
    if args.render:
        has_content = args.content or args.content_json is not None
        content = read_content(args.content, args.content_json) if has_content else None
        return render_run(args.render, content, args.out, parse_formats(args.format))
    if args.content or args.content_json or args.format or args.out:
        raise FatalError(error(Code.INVALID_REQUEST, "--content, --content-json, --format and --out only apply to --render.",
                               "Run the analysis first; write a report with `--render <run_id>` when the user asks."))
    mode = "disabled" if args.no_cache else "refresh" if args.refresh else "normal"
    options = RunOptions(cache_mode=mode)
    base = None
    if args.parent:
        store = runs.RunStore()
        base = store.request(args.parent)
        parent = json.loads(store.analysis_json(args.parent))
        store.close()
        options.parent_run_id = parent["run_id"]
        options.request_version = parent.get("request_version", 1) + 1
    data = request_from_args(args, base)
    if not data.get("topics"):
        raise FatalError(error(Code.INVALID_REQUEST, "No topic given.",
                               "Pass --request FILE, --topic TEXT, --qids Q1,Q2 or --parent RUN."))
    try:
        request = AnalysisRequest.model_validate(data)
    except ValidationError as exc:
        details = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()]
        raise FatalError(error(Code.INVALID_REQUEST, "Invalid request.", "; ".join(details))) from exc
    return run_analysis(request, options)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        envelope = execute(argv)
    except FatalError as exc:
        envelope = Envelope(status="error", errors=exc.issues)
    except ApiError as exc:
        envelope = Envelope(
            status="error",
            errors=[error(Code.API_UNAVAILABLE, f"Wikimedia API request failed: {exc}.",
                          "Temporary outage or network problem: retry in a few minutes. "
                          "Cached data from earlier runs is reused automatically.", url=exc.url,
                          http_status=exc.status)],
        )
    except SystemExit as exc:  # argparse usage errors
        if exc.code in (0, None):
            return 0
        envelope = Envelope(status="error", errors=[error(Code.INVALID_REQUEST, "Invalid arguments.",
                                                           "Run with --help for usage.")])
    except Exception as exc:  # noqa: BLE001
        log = default_cache_dir() / "debug.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a") as fh:
            fh.write(traceback.format_exc() + "\n")
        envelope = Envelope(
            status="error",
            errors=[error(Code.INTERNAL_ERROR, f"Unexpected error: {type(exc).__name__}: {exc}",
                          f"Details in {log}. Report it; do not retry with the same input.")],
        )
    sys.stdout.write(envelope.model_dump_json(indent=2, by_alias=True) + "\n")
    return envelope.exit_code


if __name__ == "__main__":
    sys.exit(main())
