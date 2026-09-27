from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "http"
sys.path.insert(0, str(ROOT / "src"))


@pytest.fixture
def replay_env(tmp_path, monkeypatch):
    """Deterministic Wikimedia: recorded responses only, fixed 'today', isolated cache, run state and working directory."""
    monkeypatch.setenv("INTEREST_SIGNALS_REPLAY_DIR", str(FIXTURES))
    monkeypatch.setenv("INTEREST_SIGNALS_TODAY", "2026-09-27")
    monkeypatch.setenv("INTEREST_SIGNALS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.chdir(tmp_path)  # reports land in the working directory
    monkeypatch.setenv("INTEREST_SIGNALS_CONTACT", "tests@example.org")
    monkeypatch.delenv("INTEREST_SIGNALS_RECORD_DIR", raising=False)
    return tmp_path
