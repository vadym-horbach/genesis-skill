"""MediaWiki Action API: search, page metadata, redirects, creation date, move log (D7).

Metadata only: no number from this module enters a metric.
"""

from __future__ import annotations

from typing import Any

from interest_signals import config
from interest_signals.cache.store import CacheStore
from interest_signals.providers.wikipedia.client import HttpClient


def api_url(project: str) -> str:
    return f"https://{project}.org/w/api.php"


def normalize_title(title: str) -> str:
    """MediaWiki display form: underscores to spaces, collapsed whitespace, first letter upper."""
    title = " ".join(title.replace("_", " ").split())
    return title[:1].upper() + title[1:] if title else title


def _page_record(page: dict[str, Any]) -> dict[str, Any]:
    props = page.get("pageprops", {})
    return {
        "page_id": page.get("pageid"),
        "title": page.get("title"),
        "qid": props.get("wikibase_item"),
        "disambiguation": "disambiguation" in props,
        "description": page.get("description"),
        "extract": page.get("extract"),
        "length": page.get("length"),
    }


class MediaWiki:
    def __init__(self, client: HttpClient, cache: CacheStore):
        self.client = client
        self.cache = cache

    def _query(self, project: str, params: dict[str, Any], endpoint: str) -> dict[str, Any]:
        base = {"action": "query", "format": "json", "formatversion": "2"}
        return self.client.get_json(api_url(project), {**base, **params}, endpoint=endpoint)

    def _cached(self, kind: str, key: str):
        value = self.cache.get_meta(kind, key)
        self.cache.record(hit=value is not None)
        return value

    # -- search -----------------------------------------------------------------------------
    def search(self, project: str, query: str) -> list[dict[str, Any]]:
        key = f"{project}|{query.strip().lower()}"
        cached = self._cached("search", key)
        if cached is not None:
            return cached
        data = self._query(
            project,
            {
                "generator": "search", "gsrsearch": query, "gsrlimit": config.SEARCH_LIMIT,
                "gsrnamespace": 0, "prop": "pageprops|description|extracts|info",
                "ppprop": "wikibase_item|disambiguation", "exintro": 1, "explaintext": 1,
                "exchars": 200, "exlimit": "max",
            },
            "mediawiki:search",
        )
        pages = data.get("query", {}).get("pages", [])
        results = sorted(
            ({**_page_record(p), "rank": p.get("index", 99)} for p in pages),
            key=lambda r: r["rank"],
        )
        self.cache.put_meta("search", key, results)
        return results

    # -- title resolution -------------------------------------------------------------------
    def resolve_titles(self, project: str, titles: list[str]) -> dict[str, dict[str, Any] | None]:
        """input title -> page record (following redirects) with `via_redirect`, or None."""
        out: dict[str, dict[str, Any] | None] = {}
        todo: list[str] = []
        for title in titles:
            cached = self._cached("page_info", f"{project}|{normalize_title(title)}")
            if cached is None:
                todo.append(title)
            else:
                out[title] = cached or None
        for i in range(0, len(todo), config.BATCH_SIZE):
            batch = todo[i : i + config.BATCH_SIZE]
            data = self._query(
                project,
                {
                    "titles": "|".join(batch), "redirects": 1,
                    "prop": "pageprops|info|description",
                    "ppprop": "wikibase_item|disambiguation",
                },
                "mediawiki:page_info",
            )
            query = data.get("query", {})
            aliases: dict[str, str] = {}
            for step in query.get("normalized", []) + query.get("redirects", []):
                aliases[step["from"]] = step["to"]
            redirected = {r["from"] for r in query.get("redirects", [])}
            pages = {p["title"]: p for p in query.get("pages", [])}
            for title in batch:
                current, via_redirect, hops = title, False, 0
                while current in aliases and hops < 5:
                    via_redirect = via_redirect or current in redirected
                    current, hops = aliases[current], hops + 1
                page = pages.get(current)
                record = None
                if page and not page.get("missing") and not page.get("invalid"):
                    record = {**_page_record(page), "via_redirect": via_redirect}
                self.cache.put_meta("page_info", f"{project}|{normalize_title(title)}", record or {})
                out[title] = record
        return out

    def redirects(self, project: str, page_id: int) -> list[str]:
        key = f"{project}|{page_id}"
        cached = self._cached("redirects", key)
        if cached is not None:
            return cached
        titles: list[str] = []
        params: dict[str, Any] = {
            "pageids": page_id, "prop": "redirects", "rdlimit": "max", "rdnamespace": 0,
            "rdprop": "title",
        }
        for _ in range(20):
            data = self._query(project, params, "mediawiki:redirects")
            for page in data.get("query", {}).get("pages", []):
                titles.extend(r["title"] for r in page.get("redirects", []))
            cont = data.get("continue")
            if not cont:
                break
            params = {**params, **cont}
        self.cache.put_meta("redirects", key, titles)
        return titles

    # -- lifecycle --------------------------------------------------------------------------
    def first_revision(self, project: str, page_id: int) -> str | None:
        key = f"{project}|{page_id}"
        cached = self._cached("first_revision", key)
        if cached is not None:
            return cached.get("timestamp")
        data = self._query(
            project,
            {"pageids": page_id, "prop": "revisions", "rvdir": "newer", "rvlimit": 1,
             "rvprop": "timestamp"},
            "mediawiki:first_revision",
        )
        pages = data.get("query", {}).get("pages", [])
        revisions = pages[0].get("revisions", []) if pages else []
        timestamp = revisions[0]["timestamp"] if revisions else None
        self.cache.put_meta("first_revision", key, {"timestamp": timestamp})
        return timestamp

    def moves_from(self, project: str, title: str) -> list[dict[str, Any]]:
        """Move log entries whose source title is `title`."""
        key = f"{project}|{normalize_title(title)}"
        cached = self._cached("moves", key)
        if cached is not None:
            return cached
        data = self._query(
            project,
            {"list": "logevents", "letype": "move", "letitle": title, "lelimit": 50,
             "leprop": "title|timestamp|details"},
            "mediawiki:moves",
        )
        entries = [
            {
                "from": e.get("title"),
                "to": (e.get("params") or {}).get("target_title"),
                "timestamp": e.get("timestamp"),
            }
            for e in data.get("query", {}).get("logevents", [])
        ]
        self.cache.put_meta("moves", key, entries)
        return entries
