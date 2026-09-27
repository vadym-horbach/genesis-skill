"""Re-record the HTTP fixtures used by replay tests and the cheap-model eval.

Runs every scenario once against the live Wikimedia APIs with the cache disabled, so each needed
response is captured. Run from the repo root:

    INTEREST_SIGNALS_CONTACT=you@example.org PYTHONPATH=src python dev/record_fixtures.py

`INTEREST_SIGNALS_TODAY` is pinned so periods match the tests. Review the diff before committing.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "http"
TODAY = "2026-09-27"

SCENARIOS = [
    ["--topic", "intermittent fasting", "--languages", "pl", "cs"],
    ["--topic", "astronomy", "--languages", "uk", "de"],
    ["--topic", "astronomy", "--languages", "uk"],
    ["--topic", "mercury", "--languages", "en"],
    ["--topic", "learning English", "--languages", "pl", "cs", "uk"],
    ["--topic", "intermittent fasting", "--topic", "ketogenic diet", "--languages", "pl", "cs"],
    ["--qids", "Q333"],
    ["--qids", "Q1666254,Q44602,Q1666254", "--languages", "pl", "cs"],
    ["--qids", "Q1666254", "--languages", "cs"],
    ["--qids", "Q1666254", "--languages", "pl"],
    ["--qids", "Q44602", "--languages", "cs"],
]


def main() -> int:
    if "--clean" in sys.argv and FIXTURES.exists():
        shutil.rmtree(FIXTURES)
    os.environ["INTEREST_SIGNALS_RECORD_DIR"] = str(FIXTURES)
    os.environ["INTEREST_SIGNALS_TODAY"] = TODAY
    os.environ.pop("INTEREST_SIGNALS_REPLAY_DIR", None)
    from interest_signals import cli

    with tempfile.TemporaryDirectory() as out:
        for args in SCENARIOS:
            code = cli.main([*args, "--no-cache", "--format", "html", "--out", out])
            print(f"exit {code}: {' '.join(args)}", file=sys.stderr)
    print(f"{len(list(FIXTURES.glob('*.json')))} fixtures in {FIXTURES}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
