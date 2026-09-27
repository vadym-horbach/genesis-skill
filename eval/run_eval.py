"""Cheap-model end-to-end evaluation through headless Claude Code (`claude -p`).

Uses the current Claude Code login (no API key). Each case runs in a fresh temporary workspace
with the skill under `.claude/skills/`, only project settings loaded, Wikimedia served from
recorded fixtures: eval/fixtures is seeded from tests/fixtures on first run (git-ignored), misses
are fetched live once and recorded there. Reports go to eval/results/ (git-ignored).

    python eval/run_eval.py                       # all cases, 1 repetition
    python eval/run_eval.py --repeat 3 --model claude-haiku-4-5
    python eval/run_eval.py --case astronomy_uk

Writes eval/results/<timestamp>.json and prints a summary. Exit 1 if pass rate < --threshold.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
EVAL_DIR = ROOT / "eval"
FIXTURES = EVAL_DIR / "fixtures"
TEST_FIXTURES = ROOT / "tests" / "fixtures" / "http"
TODAY = "2026-09-27"
LAUNCH_WORDS = re.compile(r"\b(launch (in|now)|you should launch|market size is|will make money)\b", re.I)
PERCENT = re.compile(r"[-+−]?\d+(?:\.\d+)?%")


def prepare_workspace(tmp: Path) -> Path:
    ws = tmp / "ws"
    skills = ws / ".claude" / "skills"
    skills.mkdir(parents=True)
    os.symlink(ROOT, skills / "interest-signals")
    settings = {"permissions": {"allow": ["Bash(python3:*)", "Bash(python:*)", "Read", "Glob", "Grep"]}}
    (ws / ".claude" / "settings.json").write_text(json.dumps(settings))
    return ws


def run_turn(ws: Path, prompt: str, model: str, session: str | None, env: dict[str, str]) -> dict[str, Any]:
    cmd = [
        "claude", "-p", prompt, "--model", model, "--output-format", "stream-json", "--verbose",
        "--setting-sources", "project", "--strict-mcp-config",
        "--allowedTools", "Bash", "Read", "Glob", "Grep", "Skill",
    ]
    if session:
        cmd += ["--resume", session]
    proc = subprocess.run(cmd, cwd=ws, env=env, capture_output=True, text=True, timeout=900)
    events = [json.loads(line) for line in proc.stdout.splitlines() if line.startswith("{")]
    commands, answer, session_id = [], "", session
    for ev in events:
        session_id = ev.get("session_id", session_id)
        if ev.get("type") == "assistant":
            for block in ev.get("message", {}).get("content", []):
                if block.get("type") == "tool_use" and block.get("name") == "Bash":
                    commands.append(block["input"].get("command", ""))
        if ev.get("type") == "result":
            answer = ev.get("result", "") or ""
    return {"commands": commands, "answer": answer, "session": session_id, "stderr": proc.stderr[-2000:]}


def latest_runs(cache_dir: Path) -> list[dict[str, Any]]:
    """Run state from the `runs` table of the skill's cache database, oldest first."""
    db = cache_dir / "cache.sqlite"
    if not db.exists():
        return []
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute("SELECT run_id, request, analysis, report_content FROM runs ORDER BY run_id").fetchall()
    except sqlite3.OperationalError:  # table not created yet
        rows = []
    conn.close()
    return [{"run_id": r[0], "request": json.loads(r[1]), "analysis": json.loads(r[2]),
             "report_content": json.loads(r[3]) if r[3] else None} for r in rows]


def reports(ws: Path) -> list[Path]:
    return sorted(p for p in ws.rglob("interest-signals-*") if p.suffix in (".html", ".pdf"))


def grounded(answer: str, analysis: dict[str, Any]) -> tuple[bool, list[str]]:
    """Every percentage in the answer must appear in the result's rationale or equal a stored
    growth/trend value (rounded to whole percent)."""
    allowed: set[str] = set()
    for r in analysis.get("rationale", []):
        allowed.update(PERCENT.findall(" ".join(r["sentences"])))
    for m in analysis.get("metrics", []):
        for key in ("yoy_raw", "yoy_normalized", "positive_window_share", "top_2_month_share"):
            if m.get(key) is not None:
                allowed.add(f"{m[key] * 100:+.0f}%")
                allowed.add(f"{m[key] * 100:.0f}%")
        for key in ("trend_raw", "trend_normalized"):
            t = m.get(key)
            if t:
                for f in ("annual_change", "ci_low", "ci_high"):
                    allowed.add(f"{t[f] * 100:+.0f}%")
                    allowed.add(f"{t[f] * 100:.0f}%")
    def magnitude(p: str) -> str:
        return p.replace("+", "").replace("−", "").replace("-", "")

    # Sign-insensitive: "declined 49%" states the stored -49% correctly.
    allowed_abs = {magnitude(a) for a in allowed}
    thresholds = {"95%", "100%", "50%", "70%", "40%", "5%", "80%", "0%"}
    found = PERCENT.findall(answer)
    bad = [p for p in found if magnitude(p) not in allowed_abs and magnitude(p) not in thresholds]
    return not bad, bad


GROWTH_WORDS = re.compile(r"\b(growing|grew|increas\w*|rising|rose|upward|gaining)\b", re.I)
NEGATION = re.compile(r"\b(not|no|isn't|aren't|without|declin\w*|decreas\w*|fall\w*|drop\w*)\b", re.I)


def direction_ok(answer: str, analysis: dict[str, Any]) -> tuple[bool, list[str]]:
    """When every analyzed pair declines (normalized YoY and trend both below -5%), no sentence
    may describe growth without a negation. Catches sign flips that magnitude checks miss."""
    pairs = analysis.get("metrics", [])
    declining = [
        m for m in pairs
        if m.get("yoy_normalized") is not None and m.get("trend_normalized")
        and m["yoy_normalized"] < -0.05 and m["trend_normalized"]["annual_change"] < -0.05
    ]
    if not pairs or len(declining) != len(pairs):
        return True, []
    sentences = re.split(r"(?<=[.!?\n])\s+", answer)
    bad = [s.strip()[:120] for s in sentences if GROWTH_WORDS.search(s) and not NEGATION.search(s)]
    return not bad, bad


def check(expect: dict[str, Any], turn: dict[str, Any], runs: list[dict[str, Any]], prev_runs: int,
          new_reports: list[Path]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: Any = None) -> None:
        results.append({"assertion": name, "ok": bool(ok), "detail": detail})

    analyze_calls = [c for c in turn["commands"] if "analyze.py" in c]
    new_run = runs[-1] if len(runs) > prev_runs else None
    request = new_run["request"] if new_run else {}
    analysis = new_run["analysis"] if new_run else {}
    answer = turn["answer"]

    if "status" in expect:
        if expect["status"] == "needs_confirmation":
            add("status=needs_confirmation", analyze_calls and new_run is None, analyze_calls)
        else:
            add(f"status={expect['status']}", bool(analysis), new_run["run_id"] if new_run else None)
    if "languages" in expect:
        add("languages", sorted(request.get("languages", [])) == sorted(expect["languages"]), request.get("languages"))
    if "months" in expect:
        add("months", request.get("months") == expect["months"], request.get("months"))
    if "topic_qids_any" in expect:
        qids = {q for t in request.get("topics", []) for q in t.get("qids", [])}
        add("topic", bool(qids & set(expect["topic_qids_any"])), sorted(qids))
    if "topics_min" in expect:
        add("topics_min", len(request.get("topics", [])) >= expect["topics_min"], len(request.get("topics", [])))
    if expect.get("parent"):
        add("parent_run", any("--parent" in c for c in analyze_calls) or bool(analysis.get("parent_run_id")), analyze_calls)
    if "cache_hits_min" in expect:
        hits = analysis.get("cache", {}).get("hits", 0)
        add("cache_reuse", hits >= expect["cache_hits_min"], hits)
    if "artifact" in expect:
        suffix = ".pdf" if expect["artifact"] == "report_pdf" else ".html"
        add("artifact", any(p.suffix == suffix for p in new_reports), [p.name for p in new_reports])
    if expect.get("no_report"):
        add("no_report_unasked", not new_reports, [p.name for p in new_reports])
    if "report_language" in expect:
        content = next((r["report_content"] for r in reversed(runs) if r["report_content"]), None) or {}
        add("report_language", content.get("language", "").startswith(expect["report_language"]), content.get("language"))
        add("report_has_analysis", bool(content.get("analysis")), None)
    if "answer_mentions_any" in expect:
        low = answer.lower()
        add("mentions", any(k.lower() in low for k in expect["answer_mentions_any"]), expect["answer_mentions_any"])
    if expect.get("grounded_numbers") and analysis:
        ok, bad = grounded(answer, analysis)
        add("no_invented_numbers", ok, bad)
        ok, bad = direction_ok(answer, analysis)
        add("direction_consistent", ok, bad)
    if expect.get("no_launch_claims"):
        add("no_launch_claims", not LAUNCH_WORDS.search(answer), LAUNCH_WORDS.findall(answer))
    if expect.get("answer_asks_user"):
        add("asks_user", "?" in answer, answer[-300:])
    if expect.get("no_country_claims"):
        add("no_country_numbers", not re.search(r"\*{0,2}(Poland|Germany)\*{0,2}[^.\n]{0,80}\d", answer), None)
    if "status" in expect:
        add("used_tool", bool(analyze_calls), len(analyze_calls))
    return results


def run_case(case: dict[str, Any], model: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        ws = prepare_workspace(tmp_path)
        cache_dir = tmp_path / "cache"
        env = dict(os.environ)
        env.update({
            "INTEREST_SIGNALS_REPLAY_DIR": str(FIXTURES),
            "INTEREST_SIGNALS_REPLAY_FALLBACK": "live",
            "INTEREST_SIGNALS_TODAY": TODAY,
            "INTEREST_SIGNALS_CACHE_DIR": str(cache_dir),
        })
        env.setdefault("INTEREST_SIGNALS_CONTACT", "eval@interest-signals.invalid")
        session = None
        turns_out = []
        for turn_spec in case["turns"]:
            before, before_reports = len(latest_runs(cache_dir)), set(reports(ws))
            turn = run_turn(ws, turn_spec["prompt"], model, session, env)
            session = turn["session"]
            new_reports = [p for p in reports(ws) if p not in before_reports]
            checks = check(turn_spec["expect"], turn, latest_runs(cache_dir), before, new_reports)
            turns_out.append({"prompt": turn_spec["prompt"], "commands": turn["commands"],
                              "answer": turn["answer"], "checks": checks})
        return {"id": case["id"], "turns": turns_out}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="claude-haiku-4-5")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--case", action="append")
    parser.add_argument("--threshold", type=float, default=0.9)
    args = parser.parse_args()
    if not FIXTURES.exists():
        shutil.copytree(TEST_FIXTURES, FIXTURES)
    cases = json.loads((EVAL_DIR / "cases.json").read_text())
    if args.case:
        cases = [c for c in cases if c["id"] in args.case]
    version = subprocess.run(["claude", "--version"], capture_output=True, text=True).stdout.strip()
    results = []
    for rep in range(args.repeat):
        for case in cases:
            print(f"[rep {rep + 1}] {case['id']} ...", file=sys.stderr, flush=True)
            results.append({"repetition": rep + 1, **run_case(case, args.model)})
    checks = [c for r in results for t in r["turns"] for c in t["checks"]]
    passed = sum(c["ok"] for c in checks)
    rate = passed / len(checks) if checks else 0.0
    report = {
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "model": args.model, "claude_code_version": version, "repeat": args.repeat,
        "assertions": len(checks), "passed": passed, "pass_rate": round(rate, 3), "results": results,
    }
    out_dir = EVAL_DIR / "results"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    for r in results:
        for t in r["turns"]:
            failed = [c["assertion"] for c in t["checks"] if not c["ok"]]
            mark = "PASS" if not failed else "FAIL " + ", ".join(failed)
            print(f"rep{r['repetition']} {r['id']}: {t['prompt'][:50]!r} -> {mark}")
    print(f"pass rate {rate:.1%} ({passed}/{len(checks)}), model {args.model}, {version}; report {out}")
    return 0 if rate >= args.threshold else 1


if __name__ == "__main__":
    sys.exit(main())
