"""Run directories, request versioning and follow-up lookup (D43-D45)."""

from __future__ import annotations

import json
import os
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from interest_signals.models.errors import Code, FatalError, error

DEFAULT_RUNS_DIR = "interest-signals-runs"


def runs_dir(out: str | None) -> Path:
    return Path(out or os.environ.get("INTEREST_SIGNALS_RUNS_DIR") or DEFAULT_RUNS_DIR).resolve()


def new_run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(3)


def create_run_dir(base: Path, run_id: str) -> Path:
    path = base / run_id
    path.mkdir(parents=True, exist_ok=False)
    return path


def find_run(ref: str, base: Path) -> Path:
    """Accept a run id (looked up in `base`) or a path to a run directory."""
    candidates = [Path(ref), base / ref]
    for path in candidates:
        if (path / "request.json").exists():
            return path.resolve()
    raise FatalError(
        error(
            Code.RUN_NOT_FOUND, f"Run '{ref}' not found in {base}.",
            "Pass the `run_dir` or run id printed by the previous call.", run=ref,
        )
    )


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))


def read_json(path: Path) -> Any:
    return json.loads(path.read_text())
