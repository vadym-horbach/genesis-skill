"""Record/replay HTTP transports for deterministic tests and cheap-model evals.

`INTEREST_SIGNALS_RECORD_DIR` records every real response; `INTEREST_SIGNALS_REPLAY_DIR`
serves responses only from recorded files (no network).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import parse_qsl, urlencode

import httpx


def canonical_url(url: httpx.URL | str) -> str:
    url = httpx.URL(str(url))
    query = urlencode(sorted(parse_qsl(url.query.decode(), keep_blank_values=True)))
    base = str(url.copy_with(query=None))
    return f"{base}?{query}" if query else base


def request_key(url: httpx.URL | str) -> str:
    return hashlib.sha1(canonical_url(url).encode()).hexdigest()[:24]


class ReplayMiss(httpx.TransportError):
    """No recorded response for this request."""


class RecordingTransport(httpx.BaseTransport):
    def __init__(self, directory: Path, inner: httpx.BaseTransport | None = None):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.inner = inner or httpx.HTTPTransport()

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        response = self.inner.handle_request(request)
        response.read()
        if response.status_code < 500 and response.status_code != 429:
            record = {
                "url": canonical_url(request.url),
                "status": response.status_code,
                "body": response.text,
            }
            path = self.directory / f"{request_key(request.url)}.json"
            path.write_text(json.dumps(record, ensure_ascii=False, indent=1))
        return httpx.Response(response.status_code, content=response.content, request=request)


class ReplayTransport(httpx.BaseTransport):
    """Serves recorded responses. With `fallback_live`, a miss is fetched live and recorded
    (used by the cheap-model eval, where the model may choose slightly different arguments)."""

    def __init__(self, directory: Path, fallback_live: bool = False):
        self.directory = Path(directory)
        self.served = 0
        self.recorder = RecordingTransport(self.directory) if fallback_live else None

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        path = self.directory / f"{request_key(request.url)}.json"
        if not path.exists():
            if self.recorder is not None:
                return self.recorder.handle_request(request)
            raise ReplayMiss(f"no recorded response for {canonical_url(request.url)}")
        record = json.loads(path.read_text())
        self.served += 1
        return httpx.Response(record["status"], text=record["body"], request=request)
