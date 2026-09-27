"""Deterministic topic resolution into an article cluster (D11-D16).

No LLM and no guessing: a free-text topic is auto-selected only when four explicit conditions
hold (D14); otherwise the caller gets candidates to confirm.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from interest_signals import config
from interest_signals.models.errors import Code, FatalError, Issue, error, warning
from interest_signals.models.request import TopicSpec
from interest_signals.models.result import Candidate, ClusterEntity, TopicCandidates
from interest_signals.providers.wikipedia.languages import project_for, split_languages
from interest_signals.providers.wikipedia.mediawiki import MediaWiki, normalize_title
from interest_signals.providers.wikipedia.titles import similarity
from interest_signals.providers.wikipedia.wikidata import Wikidata, pick_text


@dataclass
class ResolvedEntity:
    key: str
    qid: str | None
    label: str
    description: str | None
    selected_by: str
    sitelinks: dict[str, str]  # language -> title

    def as_model(self) -> ClusterEntity:
        return ClusterEntity(
            key=self.key, qid=self.qid, label=self.label, description=self.description,
            selected_by=self.selected_by,  # type: ignore[arg-type]
        )


@dataclass
class TopicResolution:
    topic_id: str
    query: str
    entities: list[ResolvedEntity]
    auto_selected: bool
    excluded: list[Candidate] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)


@dataclass
class _Cand:
    key: str
    qid: str | None
    pages: dict[str, dict[str, Any]] = field(default_factory=dict)  # project -> page record
    best_rank: int = 99
    exact: bool = False
    exact_via_redirect: bool = False
    title_similarity: float = 0.0
    coverage: float = 0.0
    text_match: float = 0.0
    score: float = 0.0
    label: str = ""
    description: str | None = None
    hints: list[str] = field(default_factory=list)


def score_candidate(c: _Cand) -> float:
    w = config.SCORE_WEIGHTS
    rank_score = 1.0 / c.best_rank if c.best_rank < 99 else 0.0  # best_rank: rank among relevant hits
    rank_score *= config.RANK_TEXT_FLOOR + (1 - config.RANK_TEXT_FLOOR) * c.text_match
    return round(
        w["exact_match"] * float(c.exact)
        + w["title_similarity"] * c.title_similarity
        + w["search_rank"] * rank_score
        + w["coverage"] * c.coverage,
        4,
    )


def text_match(query: str, texts: list[str | None]) -> float:
    """Share of query words (by 5-letter prefix) found in the candidate's title, description or
    extract. Down-weights search hits that share no words with the query, e.g. results of an
    English query in another language edition."""
    words = [w for w in normalize_title(query).casefold().split() if len(w) >= 3]
    if not words:
        return 1.0
    haystack = " ".join(t for t in texts if t).casefold()
    return sum(1 for w in words if w[:5] in haystack) / len(words)


def should_auto_select(ranked: list[_Cand]) -> bool:
    """D14: exact title/redirect match, rank 1 somewhere, not a disambiguation page (these are
    never candidates), and the runner-up scores below AUTO_SELECT_SECOND_RATIO of the top."""
    if not ranked:
        return False
    top = ranked[0]
    if not top.exact or top.best_rank != 1:
        return False
    if len(ranked) > 1 and ranked[1].score >= config.AUTO_SELECT_SECOND_RATIO * top.score:
        return False
    return True


class Resolver:
    def __init__(self, mediawiki: MediaWiki, wikidata: Wikidata):
        self.mw = mediawiki
        self.wd = wikidata

    # -- public -----------------------------------------------------------------------------
    def resolve(self, topic: TopicSpec, languages: list[str]) -> TopicResolution | TopicCandidates:
        if topic.qids:
            return self._from_qids(topic, languages)
        if topic.titles:
            return self._from_titles(topic, languages)
        return self._from_query(topic, languages)

    # -- explicit Wikidata ids --------------------------------------------------------------
    def _entities_from_qids(self, qids: list[str], languages: list[str]) -> list[ResolvedEntity]:
        entities = self.wd.entities(qids)
        missing = [q for q, e in entities.items() if e is None]
        if missing:
            raise FatalError(
                error(
                    Code.TOPIC_NOT_FOUND, f"Wikidata ids not found: {', '.join(missing)}.",
                    "Check the ids on wikidata.org or pass a text `query` instead.", qids=missing,
                )
            )
        out: dict[str, ResolvedEntity] = {}
        for qid in qids:
            e = entities[qid]
            canonical = e.get("id") or qid
            if canonical in out:
                continue
            out[canonical] = ResolvedEntity(
                key=canonical, qid=canonical,
                label=pick_text(e["labels"], languages) or canonical,
                description=pick_text(e["descriptions"], languages),
                selected_by="user", sitelinks=dict(e["sitelinks"]),
            )
        return list(out.values())

    def _from_qids(self, topic: TopicSpec, languages: list[str]) -> TopicResolution:
        self._check_size(topic, len(topic.qids))
        entities = self._entities_from_qids(topic.qids, languages)
        label = topic.query or ", ".join(e.label for e in entities)
        return TopicResolution(topic.topic_id or "", label, entities, auto_selected=False)

    # -- explicit titles --------------------------------------------------------------------
    def _from_titles(self, topic: TopicSpec, languages: list[str]) -> TopicResolution:
        self._check_size(topic, len(topic.titles))
        valid, lang_issues = split_languages(sorted({t.language for t in topic.titles}))
        if lang_issues:
            raise FatalError(*[i.model_copy(update={"severity": "error"}) for i in lang_issues])
        entities: dict[str, ResolvedEntity] = {}
        issues: list[Issue] = []
        for ref in topic.titles:
            page = self.mw.resolve_titles(project_for(ref.language), [ref.title])[ref.title]
            if page is None:
                raise FatalError(
                    error(
                        Code.TOPIC_NOT_FOUND, f"Page '{ref.title}' not found in {ref.language}.wikipedia.",
                        "Check the exact title or pass a text `query` instead.",
                        language=ref.language, title=ref.title,
                    )
                )
            if page["disambiguation"]:
                raise FatalError(
                    error(
                        Code.AMBIGUOUS_TOPIC,
                        f"'{page['title']}' is a disambiguation page in {ref.language}.wikipedia.",
                        "Pick one specific meaning: pass its Wikidata id or exact article title.",
                        language=ref.language, title=page["title"],
                    )
                )
            if page["via_redirect"] and similarity(ref.title, page["title"]) < 0.5:
                issues.append(
                    warning(
                        Code.RESOLUTION_LOW_CONFIDENCE,
                        f"'{ref.title}' redirects to '{page['title']}', which looks different.",
                        "Confirm this is the intended article.", title=ref.title, target=page["title"],
                    )
                )
            if page["qid"]:
                if page["qid"] in entities:
                    continue
                entity = self._entities_from_qids([page["qid"]], languages)[0]
                entity.selected_by = "user"
                entities[entity.key] = entity
            else:
                key = f"page:{ref.language}.wikipedia:{page['page_id']}"
                entities[key] = ResolvedEntity(
                    key=key, qid=None, label=page["title"], description=page.get("description"),
                    selected_by="user", sitelinks={ref.language: page["title"]},
                )
        label = topic.query or ", ".join(e.label for e in entities.values())
        return TopicResolution(topic.topic_id or "", label, list(entities.values()), False, issues=issues)

    # -- free text --------------------------------------------------------------------------
    def _from_query(self, topic: TopicSpec, languages: list[str]) -> TopicResolution | TopicCandidates:
        query = (topic.query or "").strip()
        search_languages = list(dict.fromkeys(["en", *languages]))
        cands: dict[str, _Cand] = {}

        def cand_for(project: str, page: dict[str, Any]) -> _Cand:
            key = page["qid"] or f"page:{project}:{page['page_id']}"
            c = cands.setdefault(key, _Cand(key=key, qid=page["qid"]))
            c.pages.setdefault(project, page)
            return c

        for lang in search_languages:
            project = project_for(lang)
            relevant_rank = 0
            for page in self.mw.search(project, query):
                if page["disambiguation"] or page["page_id"] is None:
                    continue
                c = cand_for(project, page)
                # Rank among hits that share words with the query; hits sharing none (typical for a
                # query in another language) are pushed behind every relevant hit.
                if text_match(query, [page["title"], page.get("description"), page.get("extract")]) > 0:
                    relevant_rank += 1
                    rank = relevant_rank
                else:
                    rank = config.SEARCH_LIMIT + page["rank"]
                c.best_rank = min(c.best_rank, rank)
                c.hints.append(f"search rank {page['rank']} in {project}")
            exact = self.mw.resolve_titles(project, [query]).get(query)
            if exact and not exact["disambiguation"]:
                c = cand_for(project, exact)
                c.exact = True
                c.exact_via_redirect = c.exact_via_redirect or exact["via_redirect"]
                c.hints.append(
                    f"query redirects to '{exact['title']}' in {project}"
                    if exact["via_redirect"]
                    else f"title matches query in {project}"
                )

        if not cands:
            raise FatalError(
                error(
                    Code.TOPIC_NOT_FOUND, f"No Wikipedia article found for '{query}'.",
                    "Try another wording, an English name, or pass Wikidata ids.", query=query,
                )
            )

        qids = [c.qid for c in cands.values() if c.qid]
        entities = self.wd.entities(qids) if qids else {}
        for c in cands.values():
            entity = entities.get(c.qid) if c.qid else None
            best_page = min(c.pages.values(), key=lambda p: p.get("rank", 99))
            c.title_similarity = max(similarity(query, p["title"]) for p in c.pages.values())
            c.text_match = max(
                text_match(query, [p["title"], p.get("description"), p.get("extract")])
                for p in c.pages.values()
            )
            if entity:
                c.label = pick_text(entity["labels"], languages) or best_page["title"]
                c.description = pick_text(entity["descriptions"], languages)
                if languages:
                    have = sum(1 for lang in languages if lang in entity["sitelinks"])
                    c.coverage = have / len(languages)
                    c.hints.append(f"articles in {have}/{len(languages)} requested languages")
                else:
                    c.coverage = 1.0
            else:
                c.label = best_page["title"]
                c.description = best_page.get("description")
            c.score = score_candidate(c)

        ranked = sorted(cands.values(), key=lambda c: (-c.score, c.best_rank, c.key))
        models = [self._candidate_model(c) for c in ranked]
        topic_id = topic.topic_id or ""
        if should_auto_select(ranked):
            top = ranked[0]
            entity = entities.get(top.qid) if top.qid else None
            sitelinks = dict(entity["sitelinks"]) if entity else {
                p.split(".")[0]: page["title"] for p, page in top.pages.items()
            }
            issues = [
                warning(
                    Code.CLUSTER_AUTO_SELECTED,
                    f"'{query}' was resolved automatically to '{top.label}' ({top.key}).",
                    "If this is the wrong article, rerun with explicit `qids` from `excluded_candidates`.",
                    topic_id=topic_id, entity=top.key,
                    match="redirect" if top.exact_via_redirect else "title",
                )
            ]
            if top.exact_via_redirect and top.title_similarity < 0.5:
                issues.append(
                    warning(
                        Code.RESOLUTION_LOW_CONFIDENCE,
                        f"'{query}' only matches '{top.label}' through a redirect.",
                        "Confirm the article or choose another candidate.", topic_id=topic_id,
                    )
                )
            resolved = ResolvedEntity(
                key=top.key, qid=top.qid, label=top.label, description=top.description,
                selected_by="auto", sitelinks=sitelinks,
            )
            return TopicResolution(
                topic_id, query, [resolved], auto_selected=True,
                excluded=models[1 : config.MAX_CANDIDATES], issues=issues,
            )
        return TopicCandidates(topic_id=topic_id, query=query, candidates=models[: config.MAX_CANDIDATES])

    @staticmethod
    def _candidate_model(c: _Cand) -> Candidate:
        project, page = min(c.pages.items(), key=lambda kv: kv[1].get("rank", 99))
        extract = page.get("extract")
        return Candidate(
            key=c.key, qid=c.qid, label=c.label, project=project, title=page["title"],
            description=c.description, extract=extract[:200] if extract else None, score=c.score,
            relation_hint=list(dict.fromkeys(c.hints)),
            provenance=[f"{p}: {pg['title']} (page_id {pg['page_id']})" for p, pg in c.pages.items()],
        )

    @staticmethod
    def _check_size(topic: TopicSpec, n: int) -> None:
        if n > config.MAX_ENTITIES_PER_CLUSTER:
            raise FatalError(
                error(
                    Code.CLUSTER_TOO_LARGE,
                    f"Topic '{topic.label}' has {n} entries; the limit is {config.MAX_ENTITIES_PER_CLUSTER}.",
                    "Keep the most specific articles; broad related pages dilute the signal.",
                    topic_id=topic.topic_id,
                )
            )

