"""One request runs the whole pipeline: resolve -> fetch -> metrics -> result -> artifacts."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from interest_signals import METHODOLOGY_VERSION, SCHEMA_VERSION, __version__, config
from interest_signals.analysis import evidence as evidence_mod
from interest_signals.analysis import ranking, rationale
from interest_signals.analysis.metrics import compute_pair_metrics
from interest_signals.analysis.periods import resolve_period
from interest_signals.cache.store import CacheStore
from interest_signals.models.envelope import Envelope
from interest_signals.models.errors import Code, FatalError, IssueLog, error
from interest_signals.models.request import AnalysisRequest, TitleRef, TopicSpec
from interest_signals.models.result import (
    AnalysisResult,
    CacheInfo,
    PairSeries,
    Scope,
    TopicCandidates,
    TopicScope,
    pair_key,
)
from interest_signals.output import render
from interest_signals.output.envelope import result_summary
from interest_signals.pipeline import runs
from interest_signals.providers.wikipedia.languages import split_languages
from interest_signals.providers.wikipedia.provider import WikipediaProvider
from interest_signals.providers.wikipedia.resolver import TopicResolution

LIFECYCLE_CODES = {Code.PAGE_CREATED_DURING_PERIOD, Code.PAGE_MOVED_DURING_PERIOD, Code.PAGE_HISTORY_CHANGED}

LIMITATIONS = [
    "Pageviews measure attention to the selected set of articles, not total demand for the topic "
    "and not unique people: one reader can open several articles.",
    "Attention is not willingness to pay, market size, competition, CAC, conversion or PMF.",
    "Language edition is not reader country: people read other-language editions, and a missing "
    "article does not mean missing interest.",
    "Country-level analysis is not supported: Wikimedia's Analytics API has no per-article "
    "breakdown by country.",
    "Merges and splits of pages are detected only approximately (edit/byte activity proxy).",
]


@dataclass
class RunOptions:
    cache_mode: str = "normal"
    out: str | None = None
    parent_run_id: str | None = None
    request_version: int = 1
    formats: list[str] | None = None


def check_request(request: AnalysisRequest, log: IssueLog) -> list[str]:
    """Validate limits, dimensions and languages. Returns valid requested languages."""
    if len(request.topics) > config.MAX_TOPICS:
        raise FatalError(
            error(
                Code.TOO_MANY_TOPICS,
                f"{len(request.topics)} topics requested; the limit is {config.MAX_TOPICS}.",
                "Split the comparison into several runs.",
            )
        )
    if "country" in request.dimensions:
        hint = (
            "Wikimedia's Analytics API has no per-article views by country. Answer with language "
            "editions only and state that language is not country."
        )
        if "language" not in request.dimensions:
            raise FatalError(
                error(Code.UNSUPPORTED_DIMENSION, "Country-level analysis is not supported.", hint,
                      dimension="country", countries=request.countries)
            )
        log.warn(Code.UNSUPPORTED_DIMENSION, "Country dimension ignored: not supported.", hint,
                 dimension="country", countries=request.countries)
    valid, issues = split_languages(request.languages)
    if request.languages and not valid:
        raise FatalError(*[i.model_copy(update={"severity": "error"}) for i in issues])
    log.extend(issues)
    return valid


def dominance_warnings(series: list[PairSeries], log: IssueLog) -> None:
    """D21: one article providing most of a multi-article cluster's recent views."""
    for s in series:
        if len(s.components) < 2:
            continue
        for c in s.components:
            if c.recent_share is not None and c.recent_share > config.DOMINANCE_SHARE:
                log.warn(
                    Code.CLUSTER_DOMINATED_BY_ENTITY,
                    f"In {s.project}, {c.entity_key} provides {c.recent_share:.0%} of the cluster's recent views.",
                    "The cluster signal mostly reflects this one article.",
                    topic_id=s.topic_id, project=s.project, entity=c.entity_key,
                )


def normalized_request(
    request: AnalysisRequest, resolutions: list[TopicResolution], languages: list[str], end_month: str
) -> dict[str, Any]:
    """request.json content: the request pinned to what was actually analyzed (resolved clusters,
    chosen languages, last month), so a follow-up changes only what the user asks to change."""
    by_id = {r.topic_id: r for r in resolutions}
    topics: list[TopicSpec] = []
    for topic in request.topics:
        r = by_id[topic.topic_id or ""]
        qids = [e.qid for e in r.entities if e.qid]
        titles = [
            TitleRef(language=next(iter(e.sitelinks)), title=next(iter(e.sitelinks.values())))
            for e in r.entities
            if not e.qid
        ]
        topics.append(TopicSpec(topic_id=topic.topic_id, query=r.query, qids=qids, titles=titles))
    pinned = {"topics": topics, "languages": languages, "end_month": end_month}
    payload = request.model_copy(update=pinned).model_dump(mode="json", exclude_none=True)
    return payload


def run_analysis(request: AnalysisRequest, options: RunOptions, provider: WikipediaProvider | None = None) -> Envelope:
    log = IssueLog()
    cache = CacheStore(mode=options.cache_mode)  # type: ignore[arg-type]
    provider = provider or WikipediaProvider(cache)
    requested = check_request(request, log)
    period = resolve_period(request.months, request.end_month)

    resolutions: list[TopicResolution] = []
    pending: list[TopicCandidates] = []
    for topic in request.topics:
        outcome = provider.resolve(topic, requested)
        if isinstance(outcome, TopicCandidates):
            pending.append(outcome)
        else:
            resolutions.append(outcome)
            log.extend(outcome.issues)
    if pending:
        return Envelope(
            status="needs_confirmation",
            summary={
                "message": "Topic is ambiguous. Ask the user which candidates to include, then "
                "rerun with `qids` for that topic.",
                "resolved_topics": {r.topic_id: [e.key for e in r.entities] for r in resolutions},
            },
            candidates=[p.model_dump(mode="json") for p in pending],
            errors=[
                error(
                    Code.AMBIGUOUS_TOPIC,
                    f"'{p.query}' does not match one article unambiguously.",
                    "Show the candidates (label, description) to the user; rerun with the chosen "
                    "`qids` (1-5 per topic). Do not pick for the user.",
                    topic_id=p.topic_id,
                )
                for p in pending
            ],
            warnings=log.items,
        )

    languages = provider.choose_languages(resolutions, requested)
    plans = [provider.plan(r, languages, requested=bool(requested)) for r in resolutions]
    series = provider.fetch(plans, period, languages)
    log.extend(provider.issues())
    if series and all(all(s == "unavailable" for s in ps.status) for ps in series):
        raise FatalError(
            error(Code.API_UNAVAILABLE, "Wikimedia APIs returned no data for any series.",
                  "Retry later; check network access to wikimedia.org.")
        )

    labels_by_topic = {r.topic_id: r.query for r in resolutions}
    metrics = [compute_pair_metrics(s) for s in series]
    for m in metrics:
        if m.months_available < config.MIN_MONTHS_FOR_GROWTH:
            log.warn(
                Code.INSUFFICIENT_HISTORY,
                f"{m.project} '{labels_by_topic[m.topic_id]}' has {m.months_available} months of data; "
                f"growth and trend need {config.MIN_MONTHS_FOR_GROWTH}.",
                "Use a longer period (months >= 15) for growth questions.",
                topic_id=m.topic_id, project=m.project,
            )
    if period.months % 12 and period.months >= config.MIN_MONTHS_FOR_GROWTH:
        log.warn(
            Code.PARTIAL_SEASONAL_CYCLE,
            f"The {period.months}-month period is not a whole number of years; the long-term trend "
            "may carry seasonal bias (year-over-year growth is not affected).",
            "Prefer 24 or 36 months.",
        )
    dominance_warnings(series, log)

    all_issues = log.items
    low_conf_topics = {i.context.get("topic_id") for i in all_issues if i.code == Code.RESOLUTION_LOW_CONFIDENCE}
    evidence = []
    for m in metrics:
        lifecycle = sum(
            1 for i in all_issues
            if i.code in LIFECYCLE_CODES and i.context.get("topic_id") == m.topic_id
            and i.context.get("project") == m.project
        )
        ctx = evidence_mod.EvidenceContext(lifecycle, m.topic_id in low_conf_topics)
        evidence.append(evidence_mod.assess(m, ctx))
    weights = request.criteria.weights if request.criteria else None
    comparison = ranking.compare(metrics, evidence, weights)
    labels = ranking.labels(metrics, evidence, comparison)
    ev_by = {pair_key(e.topic_id, e.project): e for e in evidence}
    lb_by = {pair_key(lb.topic_id, lb.project): lb for lb in labels}
    rationales = [
        rationale.explain(
            labels_by_topic[m.topic_id], m, ev_by[pair_key(m.topic_id, m.project)],
            lb_by[pair_key(m.topic_id, m.project)], comparison,
        )
        for m in metrics
    ]

    base = runs.runs_dir(options.out)
    run_id = runs.new_run_id()
    run_dir = runs.create_run_dir(base, run_id)
    request_payload = normalized_request(request, resolutions, languages, period.end)
    plan_by_topic = {p.resolution.topic_id: p for p in plans}
    scope = Scope(
        period=period,
        topics=[
            TopicScope(
                topic_id=r.topic_id, query=r.query, cluster=[e.as_model() for e in r.entities],
                auto_selected=r.auto_selected, excluded_candidates=r.excluded,
                coverage=plan_by_topic[r.topic_id].coverage,
            )
            for r in resolutions
        ],
        languages=languages,
        dimensions_analyzed=["language"],
        dimensions_unsupported=["country"] if "country" in request.dimensions else [],
        sources=provider.sources(),
    )
    result = AnalysisResult(
        schema_version=SCHEMA_VERSION, tool_version=__version__, methodology_version=METHODOLOGY_VERSION,
        run_id=run_id, parent_run_id=options.parent_run_id, request_version=options.request_version,
        created_at=datetime.now(UTC).isoformat(timespec="seconds"), request=request_payload,
        scope=scope, series=series, metrics=metrics, evidence=evidence, comparison=comparison,
        labels=labels, rationale=rationales, warnings=all_issues,
        cache=CacheInfo(
            mode=cache.mode,  # type: ignore[arg-type]
            cache_dir=str(cache.cache_dir) if cache.cache_dir else None,
            hits=cache.hits, fetched=cache.misses, http_requests=provider.client.requests,
            oldest_observation_fetched_at=cache.oldest_fetched_at,
        ),
        limitations=LIMITATIONS,
    )
    runs.write_json(run_dir / "request.json", request_payload)
    (run_dir / "analysis.json").write_text(result.model_dump_json(indent=2, by_alias=True))
    artifacts = render.render_all(result, run_dir, options.formats or request.formats)
    cache.close()
    return Envelope(
        status="ok", run_dir=str(run_dir), summary=result_summary(result, artifacts), warnings=all_issues,
    )


def render_run(run_ref: str, options: RunOptions) -> Envelope:
    run_dir = runs.find_run(run_ref, runs.runs_dir(options.out))
    path = run_dir / "analysis.json"
    if not path.exists():
        raise FatalError(error(Code.RUN_NOT_FOUND, f"{path} does not exist.", "Run the analysis first."))
    result = AnalysisResult.model_validate_json(path.read_text())
    formats = options.formats or result.request.get("formats") or ["html", "pdf"]
    artifacts = render.render_all(result, run_dir, formats)
    return Envelope(status="ok", run_dir=str(run_dir), summary=result_summary(result, artifacts),
                    warnings=result.warnings)


def setup_debug_log(path: Path) -> None:
    logging.basicConfig(filename=path, level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
