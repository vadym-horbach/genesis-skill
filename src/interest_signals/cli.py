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
from interest_signals.cache.store import CacheStore, clear_cache
from interest_signals.models.envelope import Envelope
from interest_signals.models.errors import Code, FatalError, error
from interest_signals.models.request import AnalysisRequest
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
    p.add_argument("--format", help="Comma-separated: html,pdf (default both).")
    p.add_argument("--parent", help="Previous run id or run_dir; its request is the base.")
    p.add_argument("--render", help="Re-render report/charts of an existing run without recomputing.")
    p.add_argument("--out", help="Runs directory (default ./interest-signals-runs).")
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
    if args.format:
        data["formats"] = [f.strip() for f in args.format.split(",") if f.strip()]
    return data


def cache_command(argv: list[str]) -> Envelope:
    action = argv[1] if len(argv) > 1 else "status"
    if action == "status":
        store = CacheStore()
        info = store.status()
        store.close()
        return Envelope(status="ok", summary={"cache": info})
    if action == "clear":
        return Envelope(status="ok", summary={"cache": clear_cache()})
    raise FatalError(error(Code.INVALID_REQUEST, f"Unknown cache action '{action}'.", "Use `cache status` or `cache clear`."))


def execute(argv: list[str]) -> Envelope:
    if argv and argv[0] == "cache":
        return cache_command(argv)
    args = build_parser().parse_args(argv)
    if args.version:
        return Envelope(status="ok", summary={"version": __version__})
    mode = "disabled" if args.no_cache else "refresh" if args.refresh else "normal"
    formats = [f.strip() for f in args.format.split(",")] if args.format else None
    options = RunOptions(cache_mode=mode, out=args.out, formats=formats)
    if args.render:
        return render_run(args.render, options)
    base = None
    if args.parent:
        parent_dir = runs.find_run(args.parent, runs.runs_dir(args.out))
        base = runs.read_json(parent_dir / "request.json")
        options.parent_run_id = parent_dir.name
        analysis = parent_dir / "analysis.json"
        parent_version = json.loads(analysis.read_text()).get("request_version", 1) if analysis.exists() else 1
        options.request_version = parent_version + 1
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
        log = Path(runs.runs_dir(None)) / "debug.log"
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
