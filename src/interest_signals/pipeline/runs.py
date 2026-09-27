"""Run state for follow-ups (D43-D45): the pinned request, the canonical result and the last
report content, kept in the `runs` table of the cache database, never in the working directory.

Run state persists even with `--no-cache` (that flag only bypasses cached Wikimedia data).
`cache clear` deletes it together with the cache.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from interest_signals import config
from interest_signals.cache.store import default_cache_dir
from interest_signals.models.errors import Code, FatalError, error

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    parent_run_id TEXT,
    created_at TEXT NOT NULL,
    request TEXT NOT NULL,       -- JSON: request pinned to what was analyzed
    analysis TEXT NOT NULL,      -- JSON: AnalysisResult
    report_content TEXT          -- JSON: last ReportContent passed to --render
);
"""


def new_run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(3)


class RunStore:
    def __init__(self, cache_dir: Path | None = None):
        directory = cache_dir or default_cache_dir()
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "cache.sqlite"
        self._conn = sqlite3.connect(self.path)
        self._conn.executescript(SCHEMA)
        self._prune()

    def _prune(self) -> None:
        """Drop runs older than RUN_RETENTION_DAYS; follow-ups on them need a new analysis."""
        cutoff = (datetime.now(UTC) - timedelta(days=config.RUN_RETENTION_DAYS)).isoformat()
        self._conn.execute("DELETE FROM runs WHERE created_at < ?", (cutoff,))
        self._conn.commit()

    def save(self, run_id: str, parent_run_id: str | None, request: dict[str, Any], analysis_json: str) -> None:
        self._conn.execute(
            "INSERT INTO runs (run_id, parent_run_id, created_at, request, analysis) VALUES (?, ?, ?, ?, ?)",
            (run_id, parent_run_id, datetime.now(UTC).isoformat(timespec="seconds"),
             json.dumps(request, ensure_ascii=False), analysis_json),
        )
        self._conn.commit()

    def save_report_content(self, run_id: str, content_json: str) -> None:
        self._conn.execute("UPDATE runs SET report_content = ? WHERE run_id = ?", (content_json, run_id))
        self._conn.commit()

    def _row(self, run_id: str) -> tuple[str, str, str | None]:
        row = self._conn.execute(
            "SELECT request, analysis, report_content FROM runs WHERE run_id = ?", (run_id.strip(),)
        ).fetchone()
        if row is None:
            raise FatalError(
                error(
                    Code.RUN_NOT_FOUND, f"Run '{run_id}' not found.",
                    "Pass the `summary.run_id` printed by the previous call. Runs older than "
                    f"{config.RUN_RETENTION_DAYS} days and runs removed by `cache clear` are gone: "
                    "run the analysis again.", run=run_id,
                )
            )
        return row

    def request(self, run_id: str) -> dict[str, Any]:
        return json.loads(self._row(run_id)[0])

    def analysis_json(self, run_id: str) -> str:
        return self._row(run_id)[1]

    def report_content_json(self, run_id: str) -> str | None:
        return self._row(run_id)[2]

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]

    def close(self) -> None:
        self._conn.close()
