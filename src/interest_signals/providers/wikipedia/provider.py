"""Wikipedia provider: cluster -> language projects -> pages -> monthly series (D17-D24, D34)."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from interest_signals import config
from interest_signals.analysis.periods import month_range
from interest_signals.cache.store import CacheStore
from interest_signals.models.errors import Code, FatalError, Issue, IssueLog, error
from interest_signals.models.request import TopicSpec
from interest_signals.models.result import (
    LanguageCoverage,
    MonthStatus,
    PairSeries,
    Period,
    SeriesComponent,
    SourceUse,
    TopicCandidates,
)
from interest_signals.providers.wikipedia import lifecycle
from interest_signals.providers.wikipedia.aqs import Aqs, MonthValues
from interest_signals.providers.wikipedia.client import ApiError, HttpClient
from interest_signals.providers.wikipedia.languages import project_for, top_languages
from interest_signals.providers.wikipedia.mediawiki import MediaWiki, normalize_title
from interest_signals.providers.wikipedia.resolver import Resolver, TopicResolution
from interest_signals.providers.wikipedia.titles import build_title_set
from interest_signals.providers.wikipedia.wikidata import Wikidata


@dataclass
class PageRef:
    entity_key: str
    project: str
    page_id: int
    title: str
    length: int | None
    titles: list[str] = field(default_factory=list)


@dataclass
class PageData:
    ref: PageRef
    values: dict[str, float]  # month -> summed views over the title set
    present: set[str]  # months with at least one title present in AQS
    status: dict[str, MonthStatus]


@dataclass
class TopicPlan:
    resolution: TopicResolution
    coverage: list[LanguageCoverage]
    pages: list[PageRef]


class WikipediaProvider:
    name = "wikipedia"
    unit = "pageviews (agent=user, access=all-access, monthly)"
    normalization = "article views per 1M views of the same language edition"

    def __init__(self, cache: CacheStore, client: HttpClient | None = None):
        self.client = client or HttpClient()
        self.cache = cache
        self.aqs = Aqs(self.client, cache)
        self.mw = MediaWiki(self.client, cache)
        self.wd = Wikidata(self.client, cache)
        self.resolver = Resolver(self.mw, self.wd)
        self.log = IssueLog()
        if not self.client.contact:
            self.log.warn(
                Code.UA_CONTACT_MISSING,
                "No contact in the User-Agent; Wikimedia may throttle anonymous clients.",
                "Set INTEREST_SIGNALS_CONTACT to an email or URL.",
            )

    # -- resolution -------------------------------------------------------------------------
    def resolve(self, topic: TopicSpec, languages: list[str]) -> TopicResolution | TopicCandidates:
        return self.resolver.resolve(topic, languages)

    # -- languages and pages ----------------------------------------------------------------
    def choose_languages(self, resolutions: list[TopicResolution], requested: list[str]) -> list[str]:
        if requested:
            return requested
        available = {lang for r in resolutions for e in r.entities for lang in e.sitelinks}
        chosen = top_languages(available)
        self.log.warn(
            Code.LANGUAGE_COVERAGE_LIMITED,
            f"No languages requested; analyzed the {len(chosen)} largest Wikipedia editions "
            f"with articles out of {len(available)} available.",
            "Pass `languages` to analyze specific editions.",
            analyzed=chosen, available=len(available),
        )
        return chosen

    def plan(self, resolution: TopicResolution, languages: list[str], requested: bool) -> TopicPlan:
        topic_id = resolution.topic_id
        all_langs = sorted({lang for e in resolution.entities for lang in e.sitelinks} | set(languages))
        coverage: list[LanguageCoverage] = []
        for lang in all_langs:
            present = [e.key for e in resolution.entities if lang in e.sitelinks]
            if lang in languages:
                status = "fetched" if present else "missing"
            else:
                status = "not_requested"
            coverage.append(LanguageCoverage(project=project_for(lang), status=status, entities=present))
            if lang in languages and not present and requested:
                self.log.warn(
                    Code.LANGUAGE_NOT_COVERED,
                    f"No article of topic '{resolution.query}' exists in {lang}.wikipedia.",
                    "Missing articles do not mean missing interest; readers may use another language.",
                    topic_id=topic_id, project=project_for(lang),
                )
            elif lang in languages and 0 < len(present) < len(resolution.entities):
                self.log.warn(
                    Code.CLUSTER_COVERAGE_INCOMPLETE,
                    f"Only {len(present)} of {len(resolution.entities)} cluster articles exist in "
                    f"{lang}.wikipedia; cluster totals are not fully comparable across languages.",
                    topic_id=topic_id, project=project_for(lang), present=present,
                )

        pages: list[PageRef] = []
        seen: set[tuple[str, int]] = set()
        for lang in languages:
            project = project_for(lang)
            wanted = [(e, e.sitelinks[lang]) for e in resolution.entities if lang in e.sitelinks]
            if not wanted:
                continue
            resolved = self.mw.resolve_titles(project, [t for _, t in wanted])
            for entity, title in wanted:
                page = resolved.get(title)
                if page is None or page["page_id"] is None:
                    continue
                key = (project, page["page_id"])
                if key in seen:
                    continue
                seen.add(key)
                pages.append(PageRef(entity.key, project, page["page_id"], page["title"], page.get("length")))
        if not pages:
            raise FatalError(
                error(
                    Code.EMPTY_CLUSTER,
                    f"Topic '{resolution.query}' has no articles in the analyzed languages "
                    f"({', '.join(languages)}).",
                    "Choose languages where the article exists (see `coverage`) or another topic.",
                    topic_id=topic_id, languages=languages,
                )
            )

        def with_titles(ref: PageRef) -> PageRef:
            redirects = self.mw.redirects(ref.project, ref.page_id)
            titles, truncated = build_title_set(ref.title, redirects)
            ref.titles = titles
            if truncated:
                self.log.warn(
                    Code.REDIRECTS_TRUNCATED,
                    f"{ref.project} '{ref.title}' has {len(redirects)} redirects; only "
                    f"{config.MAX_REDIRECTS_PER_PAGE} most similar titles are counted.",
                    topic_id=topic_id, project=ref.project, title=ref.title, dropped=truncated,
                )
            return ref

        pages = self.client.map(with_titles, pages)
        return TopicPlan(resolution, coverage, pages)

    # -- fetching ---------------------------------------------------------------------------
    def fetch_page(self, ref: PageRef, months: list[str], topic_id: str) -> PageData:
        status: dict[str, MonthStatus] = {}
        try:
            created = lifecycle.creation_month(self.mw.first_revision(ref.project, ref.page_id))
            title_views: dict[str, MonthValues] = {
                t: self.aqs.article_views(ref.project, t, months) for t in ref.titles
            }
        except ApiError as exc:
            self.log.warn(
                Code.PARTIAL_DATA, f"Could not fetch views for {ref.project} '{ref.title}': {exc}.",
                "Rerun later; months are marked unavailable, not zero.",
                topic_id=topic_id, project=ref.project, title=ref.title,
            )
            return PageData(ref, {}, set(), {m: "unavailable" for m in months})

        values = {m: sum(tv.get(m, (0.0, False))[0] for tv in title_views.values()) for m in months}
        present = {m for m in months if any(tv.get(m, (0.0, False))[1] for tv in title_views.values())}
        first_present = min(present) if present else None
        start_month = created or first_present
        for m in months:
            if start_month and m < start_month:
                status[m] = "not_existing"
            elif m in present:
                status[m] = "ok"
            else:
                status[m] = "zero_filled"
        if created and months[0] < created <= months[-1]:
            self.log.warn(
                Code.PAGE_CREATED_DURING_PERIOD,
                f"{ref.project} '{ref.title}' was created in {created}; earlier months are excluded.",
                topic_id=topic_id, project=ref.project, title=ref.title, month=created,
            )
        self._check_moves(ref, title_views, months, topic_id)
        self._check_history(ref, months, topic_id)
        return PageData(ref, values, present, status)

    def _check_moves(self, ref: PageRef, title_views: dict[str, MonthValues], months: list[str], topic_id: str) -> None:
        canonical = normalize_title(ref.title)
        for old in lifecycle.likely_old_titles(title_views, canonical, months):
            try:
                entries = self.mw.moves_from(ref.project, old)
            except ApiError:
                continue
            for entry in entries:
                ts = (entry.get("timestamp") or "")[:7]
                if entry.get("to") and normalize_title(entry["to"]) in ref.titles and months[0] <= ts <= months[-1]:
                    self.log.warn(
                        Code.PAGE_MOVED_DURING_PERIOD,
                        f"{ref.project} '{old}' was moved to '{entry['to']}' in {ts}; views of both "
                        "titles are summed once.",
                        topic_id=topic_id, project=ref.project, title=ref.title, old_title=old, month=ts,
                    )

    def _check_history(self, ref: PageRef, months: list[str], topic_id: str) -> None:
        try:
            net_bytes = self.aqs.page_net_bytes(ref.project, ref.title, months)
        except ApiError:
            return
        for m in lifecycle.history_change_months(months, net_bytes, ref.length):
            self.log.warn(
                Code.PAGE_HISTORY_CHANGED,
                f"{ref.project} '{ref.title}' had a rewrite-scale change in {m} "
                "(possible merge, split or major rewrite).",
                "Check the page history; attention before and after may not be comparable.",
                topic_id=topic_id, project=ref.project, title=ref.title, month=m,
            )

    def fetch(self, plans: list[TopicPlan], period: Period, languages: list[str]) -> list[PairSeries]:
        months = month_range(period.start, period.end)
        project_views: dict[str, dict[str, float] | None] = {}

        def load_project(lang: str) -> None:
            project = project_for(lang)
            try:
                values = self.aqs.project_views(project, months)
                project_views[project] = {m: v for m, (v, p) in values.items() if p}
            except ApiError as exc:
                project_views[project] = None
                self.log.warn(
                    Code.PARTIAL_DATA, f"Could not fetch total views of {project}: {exc}.",
                    "Relative attention is unavailable for this language.", project=project,
                )

        self.client.map(load_project, languages)
        series: list[PairSeries] = []
        for plan in plans:
            topic_id = plan.resolution.topic_id
            data = self.client.map(lambda r, t=topic_id: self.fetch_page(r, months, t), plan.pages)
            for lang in languages:
                project = project_for(lang)
                pages = [d for d in data if d.ref.project == project]
                if pages:
                    series.append(build_pair_series(topic_id, project, months, pages, project_views.get(project)))
        return series

    # -- provenance -------------------------------------------------------------------------
    def sources(self) -> list[SourceUse]:
        counts: Counter[str] = self.client.by_endpoint
        described = {
            "aqs:per-article": ("AQS", "pageviews/per-article/{project}/all-access/user/{title}/monthly"),
            "aqs:aggregate": ("AQS", "pageviews/aggregate/{project}/all-access/user/monthly"),
            "aqs:bytes-difference/net/per-page": (
                "AQS", "bytes-difference/net/per-page/{project}/{title}/all-editor-types/monthly"),
            "mediawiki:search": ("MediaWiki Action API", "query&generator=search"),
            "mediawiki:page_info": ("MediaWiki Action API", "query&prop=pageprops|info|description"),
            "mediawiki:redirects": ("MediaWiki Action API", "query&prop=redirects"),
            "mediawiki:first_revision": ("MediaWiki Action API", "query&prop=revisions&rvdir=newer"),
            "mediawiki:moves": ("MediaWiki Action API", "query&list=logevents&letype=move"),
            "wikidata:wbgetentities": ("Wikidata API", "wbgetentities&props=sitelinks|labels|descriptions"),
        }
        return [
            SourceUse(api=api, endpoint=endpoint, requests=counts.get(key, 0))
            for key, (api, endpoint) in described.items()
            if counts.get(key, 0)
        ]

    def issues(self) -> list[Issue]:
        return self.log.items


def build_pair_series(
    topic_id: str, project: str, months: list[str], pages: list[PageData],
    project_views: dict[str, float] | None,
) -> PairSeries:
    """Aggregate raw page observations into one cluster series for a language project (D20).

    Derived metrics are later computed from this aggregated series only; nothing is averaged
    across articles."""
    views: list[float | None] = []
    statuses: list[MonthStatus] = []
    for m in months:
        page_status = [p.status[m] for p in pages]
        if "unavailable" in page_status:
            statuses.append("unavailable")
            views.append(None)
        elif all(s == "not_existing" for s in page_status):
            statuses.append("not_existing")
            views.append(None)
        else:
            total = sum(p.values.get(m, 0.0) for p in pages if p.status[m] in ("ok", "zero_filled"))
            statuses.append("ok" if any(s == "ok" for s in page_status) else "zero_filled")
            views.append(total)
    totals: list[float | None] = []
    per_million: list[float | None] = []
    for m, v in zip(months, views):
        total = project_views.get(m) if project_views else None
        totals.append(total)
        per_million.append(v / total * 1e6 if v is not None and total else None)
    recent = [m for m, s in zip(months, statuses) if s in ("ok", "zero_filled")][-config.RECENT_MONTHS:]
    recent_total = sum(p.values.get(m, 0.0) for p in pages for m in recent)
    components = [
        SeriesComponent(
            entity_key=p.ref.entity_key, page_id=p.ref.page_id, titles=p.ref.titles,
            views=[p.values.get(m) if p.status[m] in ("ok", "zero_filled") else None for m in months],
            recent_share=(sum(p.values.get(m, 0.0) for m in recent) / recent_total) if recent_total else None,
        )
        for p in pages
    ]
    return PairSeries(
        topic_id=topic_id, project=project, months=months, views=views, project_views=totals,
        per_million=per_million, status=statuses, components=components,
    )

