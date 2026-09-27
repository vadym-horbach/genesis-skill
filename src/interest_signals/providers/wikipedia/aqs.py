"""Wikimedia Analytics API (AQS): the only source of numbers used in metrics (D6).

All series are monthly, `agent=user`, `access=all-access`. Observations are cached per month so a
wider follow-up request downloads only the missing months (D39).
"""

from __future__ import annotations

import calendar
from urllib.parse import quote

from interest_signals.analysis.periods import add_months
from interest_signals.cache.store import CacheStore
from interest_signals.providers.wikipedia.client import HttpClient

BASE = "https://wikimedia.org/api/rest_v1/metrics"
ACCESS = "all-access"
AGENT = "user"

MonthValues = dict[str, tuple[float, bool]]  # month -> (value, present in API response)


def encode_title(title: str) -> str:
    return quote(title.replace(" ", "_"), safe="")


def _pv_start(month: str) -> str:
    return month.replace("-", "") + "0100"


def _pv_end(month: str) -> str:
    year, mon = int(month[:4]), int(month[5:7])
    return f"{year:04d}{mon:02d}{calendar.monthrange(year, mon)[1]:02d}00"


def _day(month: str) -> str:
    return month.replace("-", "") + "01"


def _missing_span(months: list[str], cached: MonthValues) -> tuple[str, str] | None:
    missing = [m for m in months if m not in cached]
    if not missing:
        return None
    return min(missing), max(missing)


class Aqs:
    def __init__(self, client: HttpClient, cache: CacheStore):
        self.client = client
        self.cache = cache

    def _series(self, kind: str, project: str, key: str, months: list[str], fetch) -> MonthValues:
        cached = self.cache.get_monthly(kind, project, key, months)
        span = _missing_span(months, cached)
        self.cache.record(hit=span is None)
        if span is None:
            return cached
        fetched = fetch(span[0], span[1])
        rows: MonthValues = {}
        for month in months:
            if span[0] <= month <= span[1]:
                value = fetched.get(month)
                rows[month] = (float(value), True) if value is not None else (0.0, False)
        self.cache.put_monthly(kind, project, key, rows)
        return {**cached, **rows}

    # -- pageviews --------------------------------------------------------------------------
    def article_views(self, project: str, title: str, months: list[str]) -> MonthValues:
        def fetch(start: str, end: str) -> dict[str, float]:
            url = (
                f"{BASE}/pageviews/per-article/{project}/{ACCESS}/{AGENT}/"
                f"{encode_title(title)}/monthly/{_pv_start(start)}/{_pv_end(end)}"
            )
            data = self.client.get_json(url, endpoint="aqs:per-article", not_found_ok=True)
            items = (data or {}).get("items", [])
            return {f"{i['timestamp'][:4]}-{i['timestamp'][4:6]}": i["views"] for i in items}

        return self._series("article", project, title, months, fetch)

    def project_views(self, project: str, months: list[str]) -> MonthValues:
        def fetch(start: str, end: str) -> dict[str, float]:
            url = (
                f"{BASE}/pageviews/aggregate/{project}/{ACCESS}/{AGENT}/monthly/"
                f"{_pv_start(start)}/{_pv_end(end)}"
            )
            data = self.client.get_json(url, endpoint="aqs:aggregate", not_found_ok=True)
            items = (data or {}).get("items", [])
            return {f"{i['timestamp'][:4]}-{i['timestamp'][4:6]}": i["views"] for i in items}

        return self._series("project", project, "", months, fetch)

    # -- edit activity (lifecycle signal) ---------------------------------------------------
    def _per_page_results(self, path: str, project: str, title: str, start: str, end: str, field: str):
        url = (
            f"{BASE}/{path}/{project}/{encode_title(title)}/all-editor-types/monthly/"
            f"{_day(start)}/{_day(add_months(end, 1))}"
        )
        data = self.client.get_json(url, endpoint=f"aqs:{path}", not_found_ok=True)
        items = (data or {}).get("items", [])
        results = items[0].get("results", []) if items else []
        return {r["timestamp"][:7]: r[field] for r in results}

    def page_net_bytes(self, project: str, title: str, months: list[str]) -> MonthValues:
        """Net byte change per month. Net (not absolute) so vandalism plus revert cancels out."""
        return self._series(
            "net_bytes", project, title, months,
            lambda s, e: self._per_page_results(
                "bytes-difference/net/per-page", project, title, s, e, "net_bytes_diff"
            ),
        )
