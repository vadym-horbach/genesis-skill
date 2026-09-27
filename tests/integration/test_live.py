"""Real Wikimedia API checks. Deselected by default; run with `pytest -m live` before a release."""

from __future__ import annotations

import pytest

from interest_signals.analysis.periods import month_range
from interest_signals.cache.store import CacheStore
from interest_signals.providers.wikipedia.aqs import Aqs
from interest_signals.providers.wikipedia.client import HttpClient
from interest_signals.providers.wikipedia.mediawiki import MediaWiki
from interest_signals.providers.wikipedia.wikidata import Wikidata

pytestmark = pytest.mark.live


@pytest.fixture
def parts(tmp_path, monkeypatch):
    monkeypatch.delenv("INTEREST_SIGNALS_REPLAY_DIR", raising=False)
    monkeypatch.delenv("INTEREST_SIGNALS_RECORD_DIR", raising=False)
    client = HttpClient()
    cache = CacheStore(cache_dir=tmp_path)
    return client, cache


def test_search_and_page_info(parts):
    mw = MediaWiki(*parts)
    hits = mw.search("en.wikipedia", "astronomy")
    assert any(h["qid"] == "Q333" for h in hits)
    page = mw.resolve_titles("en.wikipedia", ["astronomy"])["astronomy"]
    assert page["qid"] == "Q333" and page["page_id"]
    assert mw.redirects("en.wikipedia", page["page_id"])
    assert mw.first_revision("en.wikipedia", page["page_id"]).startswith("20")


def test_langlinks_via_wikidata(parts):
    entity = Wikidata(*parts).entities(["Q333"])["Q333"]
    assert entity["sitelinks"]["uk"] == "Астрономія"
    assert "de" in entity["sitelinks"]


def test_pageviews_project_views_and_cache(parts):
    client, cache = parts
    aqs = Aqs(client, cache)
    months = month_range("2025-01", "2025-06")
    views = aqs.article_views("en.wikipedia", "Astronomy", months)
    assert len(views) == 6 and all(p for _, p in views.values())
    total = aqs.project_views("en.wikipedia", months)
    assert all(v > 1e8 for v, _ in total.values())
    before = client.requests
    aqs.article_views("en.wikipedia", "Astronomy", months)
    assert client.requests == before


def test_edits_and_moves_endpoints(parts):
    client, cache = parts
    aqs = Aqs(client, cache)
    net = aqs.page_net_bytes("en.wikipedia", "Astronomy", month_range("2025-01", "2025-06"))
    assert len(net) == 6
    assert isinstance(MediaWiki(client, cache).moves_from("en.wikipedia", "Astronomy"), list)
