"""HTTP client for Wikimedia APIs: User-Agent policy, rate limit, retries (D9)."""

from __future__ import annotations

import os
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, TypeVar

import httpx

from interest_signals import __version__, config
from interest_signals.providers.wikipedia.replay import (
    RecordingTransport,
    ReplayMiss,
    ReplayTransport,
)

T = TypeVar("T")
R = TypeVar("R")


class ApiError(Exception):
    def __init__(self, message: str, url: str, status: int | None = None):
        super().__init__(message)
        self.url = url
        self.status = status


def user_agent(contact: str | None) -> str:
    parts = [config.REPO_URL]
    if contact:
        parts.append(contact)
    return f"interest-signals/{__version__} ({'; '.join(parts)}) httpx/{httpx.__version__}"


def transport_from_env() -> httpx.BaseTransport | None:
    replay = os.environ.get("INTEREST_SIGNALS_REPLAY_DIR")
    if replay:
        fallback = os.environ.get("INTEREST_SIGNALS_REPLAY_FALLBACK") == "live"
        return ReplayTransport(Path(replay), fallback_live=fallback)
    record = os.environ.get("INTEREST_SIGNALS_RECORD_DIR")
    if record:
        return RecordingTransport(Path(record))
    return None


class HttpClient:
    def __init__(
        self,
        transport: httpx.BaseTransport | None = None,
        requests_per_minute: float | None = config.REQUESTS_PER_MINUTE,
        contact: str | None = None,
        sleep: Callable[[float], None] | None = None,
    ):
        if transport is None:
            transport = transport_from_env()
        if isinstance(transport, ReplayTransport) and transport.recorder is None:
            requests_per_minute = None
        self.contact = contact if contact is not None else os.environ.get("INTEREST_SIGNALS_CONTACT")
        self._client = httpx.Client(
            headers={"User-Agent": user_agent(self.contact), "Accept": "application/json"},
            timeout=config.TIMEOUT_SECONDS,
            transport=transport,
            follow_redirects=True,
        )
        self._interval = 60.0 / requests_per_minute if requests_per_minute else 0.0
        self._slot_lock = threading.Lock()
        self._next_slot = 0.0
        self._sleep = sleep or time.sleep
        self._count_lock = threading.Lock()
        self.requests = 0
        self.by_endpoint: Counter[str] = Counter()

    def _wait_for_slot(self) -> None:
        if not self._interval:
            return
        with self._slot_lock:
            now = time.monotonic()
            slot = max(now, self._next_slot)
            self._next_slot = slot + self._interval
        delay = slot - time.monotonic()
        if delay > 0:
            self._sleep(delay)

    def get_json(
        self, url: str, params: dict[str, Any] | None = None, endpoint: str = "other",
        not_found_ok: bool = False,
    ) -> Any | None:
        """GET JSON with retries. Returns None for 404 when `not_found_ok`."""
        last_error = "unknown error"
        for attempt in range(config.MAX_RETRIES):
            self._wait_for_slot()
            with self._count_lock:
                self.requests += 1
                self.by_endpoint[endpoint] += 1
            try:
                response = self._client.get(url, params=params)
            except ReplayMiss as exc:
                raise ApiError(str(exc), url) from exc
            except httpx.TransportError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                self._sleep(min(2**attempt, 30))
                continue
            if response.status_code == 404 and not_found_ok:
                return None
            if response.status_code == 429 or response.status_code >= 500:
                last_error = f"HTTP {response.status_code}"
                retry_after = response.headers.get("Retry-After", "")
                wait = float(retry_after) if retry_after.isdigit() else min(2**attempt, 30)
                self._sleep(wait)
                continue
            if response.status_code >= 400:
                raise ApiError(f"HTTP {response.status_code}", str(response.url), response.status_code)
            return response.json()
        raise ApiError(f"gave up after {config.MAX_RETRIES} attempts ({last_error})", url)

    def map(self, fn: Callable[[T], R], items: Iterable[T]) -> list[R]:
        items = list(items)
        if len(items) <= 1:
            return [fn(i) for i in items]
        with ThreadPoolExecutor(max_workers=config.CONCURRENCY) as pool:
            return list(pool.map(fn, items))

    def close(self) -> None:
        self._client.close()
