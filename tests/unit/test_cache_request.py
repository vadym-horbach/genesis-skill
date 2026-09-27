from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from interest_signals.analysis.periods import month_range
from interest_signals.cache.store import CacheStore, clear_cache
from interest_signals.models.request import AnalysisRequest
from interest_signals.providers.wikipedia.aqs import Aqs


class FakeClient:
    """Serves AQS-like monthly items for any requested span and records the spans."""

    def __init__(self):
        self.calls: list[str] = []

    def get_json(self, url, params=None, endpoint="", not_found_ok=False):
        self.calls.append(url)
        start, end = url.rstrip("/").split("/")[-2:]
        months = month_range(f"{start[:4]}-{start[4:6]}", f"{end[:4]}-{end[4:6]}")
        return {"items": [{"timestamp": m.replace("-", "") + "0100", "views": 10} for m in months]}


def test_follow_up_downloads_only_missing(tmp_path):
    cache = CacheStore(cache_dir=tmp_path)
    client = FakeClient()
    aqs = Aqs(client, cache)
    first = month_range("2024-09", "2026-08")
    for project in ("pl.wikipedia", "cs.wikipedia"):
        aqs.article_views(project, "Topic", first)
    assert len(client.calls) == 2
    client.calls.clear()
    wider = month_range("2023-09", "2026-08")
    for project in ("pl.wikipedia", "cs.wikipedia", "uk.wikipedia"):
        values = aqs.article_views(project, "Topic", wider)
        assert len(values) == 36
    assert len(client.calls) == 3
    pl_call = next(c for c in client.calls if "/pl.wikipedia/" in c)
    assert pl_call.endswith("/2023090100/2024083100")
    client.calls.clear()
    aqs.article_views("uk.wikipedia", "Topic", wider)
    assert client.calls == []


def test_refresh_and_disabled_modes(tmp_path):
    months = month_range("2025-01", "2025-03")
    CacheStore(cache_dir=tmp_path).put_monthly("article", "p", "T", {m: (1.0, True) for m in months})
    assert len(CacheStore(cache_dir=tmp_path).get_monthly("article", "p", "T", months)) == 3
    assert CacheStore(mode="refresh", cache_dir=tmp_path).get_monthly("article", "p", "T", months) == {}
    disabled = CacheStore(mode="disabled", cache_dir=tmp_path / "never")
    assert disabled.cache_dir is None
    assert not (tmp_path / "never").exists()


def test_month_freshness_rule():
    old = (datetime(2025, 1, 31, tzinfo=UTC) + timedelta(days=10)).isoformat()
    assert CacheStore.month_is_fresh("2025-01", old)
    young = datetime(2025, 2, 1, tzinfo=UTC).isoformat()
    now = datetime(2025, 2, 1, 12, tzinfo=UTC)
    assert CacheStore.month_is_fresh("2025-01", young, now)
    assert not CacheStore.month_is_fresh("2025-01", young, now + timedelta(days=2))


def test_meta_roundtrip_status_and_clear(tmp_path):
    store = CacheStore(cache_dir=tmp_path)
    store.put_meta("entity", "Q1", {"a": 1})
    assert store.get_meta("entity", "Q1") == {"a": 1}
    assert store.status()["metadata_entries"] == 1
    store.close()
    assert clear_cache(tmp_path)["removed"] is True


def test_request_defaults_and_topic_ids():
    r = AnalysisRequest.model_validate({"topics": [{"query": "a"}, {"qids": ["q42"]}], "languages": ["PL"]})
    assert [t.topic_id for t in r.topics] == ["t1", "t2"]
    assert r.topics[1].qids == ["Q42"]
    assert r.languages == ["pl"] and r.months == 24 and r.formats == ["html", "pdf"]


def test_request_countries_add_dimension():
    r = AnalysisRequest.model_validate({"topics": [{"query": "a"}], "countries": ["PL"]})
    assert "country" in r.dimensions


@pytest.mark.parametrize(
    "payload",
    [
        {"topics": []},
        {"topics": [{}]},
        {"topics": [{"qids": ["42"]}]},
        {"topics": [{"query": "a"}], "months": 0},
        {"topics": [{"query": "a"}], "criteria": {"weights": {"magic": 1}}},
        {"topics": [{"query": "a"}], "criteria": {"weights": {"growth": 0}}},
        {"topics": [{"query": "a"}], "end_month": "2025-13"},
    ],
)
def test_request_rejects_invalid(payload):
    with pytest.raises(ValidationError):
        AnalysisRequest.model_validate(payload)


def test_schema_version_change_clears_cache(tmp_path, monkeypatch):
    from interest_signals import config

    store = CacheStore(cache_dir=tmp_path)
    store.put_meta("entity", "Q1", {"a": 1})
    store.close()
    monkeypatch.setattr(config, "CACHE_SCHEMA_VERSION", config.CACHE_SCHEMA_VERSION + 1)
    assert CacheStore(cache_dir=tmp_path).get_meta("entity", "Q1") is None
