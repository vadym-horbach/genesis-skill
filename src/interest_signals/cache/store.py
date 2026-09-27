"""Persistent SQLite cache of granular raw observations and metadata (D38-D42).

Only raw provider data is cached. Derived metrics, rankings, labels, charts and reports are
always recomputed from these observations.
"""

from __future__ import annotations

import calendar
import json
import os
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from interest_signals import config

Mode = Literal["normal", "refresh", "disabled"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS monthly (
    kind TEXT NOT NULL,          -- article | project | net_bytes
    project TEXT NOT NULL,
    key TEXT NOT NULL,           -- page title, '' for project totals
    month TEXT NOT NULL,         -- YYYY-MM
    value REAL NOT NULL,
    present INTEGER NOT NULL,    -- 0 when the API omitted the month (no activity)
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (kind, project, key, month)
);
CREATE TABLE IF NOT EXISTS meta (
    kind TEXT NOT NULL,          -- page_info | entity | search | first_revision | moves | resolution
    key TEXT NOT NULL,
    value TEXT NOT NULL,         -- JSON
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (kind, key)
);
CREATE TABLE IF NOT EXISTS info (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def default_cache_dir() -> Path:
    env = os.environ.get("INTEREST_SIGNALS_CACHE_DIR")
    if env:
        return Path(env).expanduser()
    import platformdirs

    return Path(platformdirs.user_cache_dir("interest-signals"))


def utcnow() -> datetime:
    return datetime.now(UTC)


def month_end(month: str) -> datetime:
    year, mon = int(month[:4]), int(month[5:7])
    last = calendar.monthrange(year, mon)[1]
    return datetime(year, mon, last, 23, 59, 59, tzinfo=UTC)


class CacheStore:
    def __init__(self, mode: Mode = "normal", cache_dir: Path | None = None):
        self.mode = mode
        self.cache_dir = None if mode == "disabled" else (cache_dir or default_cache_dir())
        if self.cache_dir is None:
            target = ":memory:"
        else:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            target = str(self.cache_dir / "cache.sqlite")
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(target, check_same_thread=False)
        self._migrate()
        self.hits = 0
        self.misses = 0
        self._oldest: str | None = None

    # -- schema -----------------------------------------------------------------------------
    def _migrate(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.executescript(SCHEMA)
            row = cur.execute("SELECT value FROM info WHERE key='schema_version'").fetchone()
            version = str(config.CACHE_SCHEMA_VERSION)
            if row is not None and row[0] != version:
                cur.executescript("DELETE FROM monthly; DELETE FROM meta;")
            cur.execute("INSERT OR REPLACE INTO info VALUES ('schema_version', ?)", (version,))
            self._conn.commit()

    # -- helpers ----------------------------------------------------------------------------
    def _note_used(self, fetched_at: str) -> None:
        if self._oldest is None or fetched_at < self._oldest:
            self._oldest = fetched_at

    @staticmethod
    def month_is_fresh(month: str, fetched_at: str, now: datetime | None = None) -> bool:
        fetched = datetime.fromisoformat(fetched_at)
        if fetched - month_end(month) >= timedelta(days=config.IMMUTABLE_AFTER_DAYS):
            return True
        now = now or utcnow()
        return now - fetched < timedelta(hours=config.RECENT_MONTH_TTL_HOURS)

    # -- monthly observations ---------------------------------------------------------------
    def get_monthly(
        self, kind: str, project: str, key: str, months: list[str]
    ) -> dict[str, tuple[float, bool]]:
        """Fresh cached rows for the requested months. Missing or stale months are absent."""
        if self.mode != "normal" or not months:
            return {}
        with self._lock:
            rows = self._conn.execute(
                "SELECT month, value, present, fetched_at FROM monthly "
                "WHERE kind=? AND project=? AND key=? AND month BETWEEN ? AND ?",
                (kind, project, key, min(months), max(months)),
            ).fetchall()
        wanted = set(months)
        out: dict[str, tuple[float, bool]] = {}
        for month, value, present, fetched_at in rows:
            if month in wanted and self.month_is_fresh(month, fetched_at):
                out[month] = (value, bool(present))
                self._note_used(fetched_at)
        return out

    def put_monthly(
        self, kind: str, project: str, key: str, rows: dict[str, tuple[float, bool]]
    ) -> None:
        if not rows:
            return
        now = utcnow().isoformat()
        with self._lock:
            self._conn.executemany(
                "INSERT OR REPLACE INTO monthly VALUES (?,?,?,?,?,?,?)",
                [(kind, project, key, m, v, int(p), now) for m, (v, p) in rows.items()],
            )
            self._conn.commit()

    # -- metadata ---------------------------------------------------------------------------
    def get_meta(self, kind: str, key: str) -> Any | None:
        if self.mode != "normal":
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT value, fetched_at FROM meta WHERE kind=? AND key=?", (kind, key)
            ).fetchone()
        if row is None:
            return None
        value, fetched_at = row
        if utcnow() - datetime.fromisoformat(fetched_at) > timedelta(days=config.METADATA_TTL_DAYS):
            return None
        self._note_used(fetched_at)
        return json.loads(value)

    def put_meta(self, kind: str, key: str, value: Any) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO meta VALUES (?,?,?,?)",
                (kind, key, json.dumps(value, ensure_ascii=False), utcnow().isoformat()),
            )
            self._conn.commit()

    # -- accounting -------------------------------------------------------------------------
    def record(self, hit: bool) -> None:
        with self._lock:
            if hit:
                self.hits += 1
            else:
                self.misses += 1

    @property
    def oldest_fetched_at(self) -> str | None:
        return self._oldest

    # -- maintenance ------------------------------------------------------------------------
    def status(self) -> dict[str, Any]:
        with self._lock:
            monthly = self._conn.execute("SELECT COUNT(*), MIN(fetched_at) FROM monthly").fetchone()
            meta = self._conn.execute("SELECT COUNT(*), MIN(fetched_at) FROM meta").fetchone()
        path = None if self.cache_dir is None else self.cache_dir / "cache.sqlite"
        size = path.stat().st_size if path and path.exists() else 0
        oldest = min([x for x in (monthly[1], meta[1]) if x], default=None)
        return {
            "cache_dir": str(self.cache_dir) if self.cache_dir else None,
            "size_bytes": size,
            "monthly_observations": monthly[0],
            "metadata_entries": meta[0],
            "oldest_fetched_at": oldest,
        }

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def clear_cache(cache_dir: Path | None = None) -> dict[str, Any]:
    target = (cache_dir or default_cache_dir()) / "cache.sqlite"
    existed = target.exists()
    if existed:
        target.unlink()
    return {"cache_dir": str(target.parent), "removed": existed}
