"""Wikidata API: entity labels, descriptions and Wikipedia sitelinks (metadata only, D7)."""

from __future__ import annotations

from typing import Any

from interest_signals import config
from interest_signals.cache.store import CacheStore
from interest_signals.providers.wikipedia.client import HttpClient

API = "https://www.wikidata.org/w/api.php"
NON_WIKIPEDIA_SITES = {
    "commonswiki", "specieswiki", "metawiki", "mediawikiwiki", "wikidatawiki", "sourceswiki",
    "outreachwiki", "wikimaniawiki", "foundationwiki", "wikifunctionswiki", "incubatorwiki",
}
SITE_LANGUAGE_ALIASES = {"be-x-old": "be-tarask"}


def site_to_language(site: str) -> str | None:
    if not site.endswith("wiki") or site in NON_WIKIPEDIA_SITES:
        return None
    lang = site[: -len("wiki")].replace("_", "-")
    return SITE_LANGUAGE_ALIASES.get(lang, lang)


def pick_text(values: dict[str, Any], languages: list[str]) -> str | None:
    for lang in [*languages, "en", "mul"]:
        if lang in values:
            return values[lang]["value"]
    if values:
        return next(iter(values.values()))["value"]
    return None


class Wikidata:
    def __init__(self, client: HttpClient, cache: CacheStore):
        self.client = client
        self.cache = cache

    def entities(self, qids: list[str]) -> dict[str, dict[str, Any] | None]:
        """qid -> {id, labels, descriptions, sitelinks{language: title}} or None when missing."""
        out: dict[str, dict[str, Any] | None] = {}
        todo: list[str] = []
        for qid in qids:
            cached = self.cache.get_meta("entity", qid)
            self.cache.record(hit=cached is not None)
            if cached is None:
                todo.append(qid)
            else:
                out[qid] = cached or None
        todo = sorted(set(todo), key=lambda q: int(q[1:]))  # deterministic requests (cache, replay)
        for i in range(0, len(todo), config.BATCH_SIZE):
            batch = todo[i : i + config.BATCH_SIZE]
            data = self.client.get_json(
                API,
                {
                    "action": "wbgetentities", "ids": "|".join(batch), "format": "json",
                    "props": "sitelinks|labels|descriptions",
                },
                endpoint="wikidata:wbgetentities",
            )
            entities = data.get("entities", {})
            for qid in batch:
                raw = entities.get(qid)
                parsed = self._parse(raw)
                self.cache.put_meta("entity", qid, parsed or {})
                out[qid] = parsed
        return out

    @staticmethod
    def _parse(raw: dict[str, Any] | None) -> dict[str, Any] | None:
        if not raw or "missing" in raw:
            return None
        sitelinks: dict[str, str] = {}
        for site, link in raw.get("sitelinks", {}).items():
            lang = site_to_language(site)
            if lang:
                sitelinks[lang] = link["title"]
        return {
            "id": raw.get("id"),
            "labels": raw.get("labels", {}),
            "descriptions": raw.get("descriptions", {}),
            "sitelinks": sitelinks,
        }
