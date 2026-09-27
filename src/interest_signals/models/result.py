"""AnalysisResult: the canonical output (analysis.json). Every other artifact is rendered from it."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from interest_signals.models.errors import Issue

MonthStatus = Literal["ok", "zero_filled", "not_existing", "unavailable"]
CoverageStatus = Literal["fetched", "not_requested", "missing", "unsupported"]
EvidenceLevel = Literal["high", "medium", "low"]
LabelName = Literal[
    "candidate for further validation", "monitor", "weaker signal", "insufficient evidence"
]


def pair_key(topic_id: str, project: str) -> str:
    return f"{topic_id}:{project}"


class Period(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    start: str = Field(alias="from")
    end: str = Field(alias="to")
    months: int


class Candidate(BaseModel):
    key: str
    qid: str | None = None
    label: str
    project: str
    title: str
    description: str | None = None
    extract: str | None = None
    score: float
    relation_hint: list[str] = Field(default_factory=list)
    provenance: list[str] = Field(default_factory=list)


class TopicCandidates(BaseModel):
    topic_id: str
    query: str
    candidates: list[Candidate]


class ClusterEntity(BaseModel):
    key: str
    qid: str | None = None
    label: str
    description: str | None = None
    selected_by: Literal["user", "auto"]


class LanguageCoverage(BaseModel):
    project: str
    status: CoverageStatus
    entities: list[str] = Field(default_factory=list)


class TopicScope(BaseModel):
    topic_id: str
    query: str
    cluster: list[ClusterEntity]
    auto_selected: bool
    excluded_candidates: list[Candidate] = Field(default_factory=list)
    coverage: list[LanguageCoverage] = Field(default_factory=list)


class SourceUse(BaseModel):
    api: str
    endpoint: str
    requests: int


class Scope(BaseModel):
    period: Period
    topics: list[TopicScope]
    languages: list[str]
    dimensions_analyzed: list[str]
    dimensions_unsupported: list[str] = Field(default_factory=list)
    traffic: dict[str, str] = Field(
        default_factory=lambda: {"agent": "user", "access": "all-access", "granularity": "monthly"}
    )
    sources: list[SourceUse] = Field(default_factory=list)


class SeriesComponent(BaseModel):
    entity_key: str
    page_id: int | None
    titles: list[str]
    views: list[float | None]
    recent_share: float | None = None


class PairSeries(BaseModel):
    topic_id: str
    project: str
    months: list[str]
    views: list[float | None]
    project_views: list[float | None]
    per_million: list[float | None]
    status: list[MonthStatus]
    components: list[SeriesComponent]


class TrendStat(BaseModel):
    annual_change: float
    ci_low: float
    ci_high: float
    slope_log: float
    intercept_log: float
    points: int
    log_offset: float


class PairMetrics(BaseModel):
    topic_id: str
    project: str
    months_available: int
    zero_months: int
    unavailable_months: int
    recent_views: float | None = None
    recent_per_million: float | None = None
    yoy_raw: float | None = None
    yoy_normalized: float | None = None
    trend_raw: TrendStat | None = None
    trend_normalized: TrendStat | None = None
    positive_window_share: float | None = None
    windows: int = 0
    spikes: list[str] = Field(default_factory=list)
    spike_ratio: float | None = None
    top_2_month_share: float | None = None
    volatility: float | None = None
    not_computed: dict[str, str] = Field(default_factory=dict)


class EvidenceReason(BaseModel):
    rule_id: str
    effect: Literal["low", "blocks_high"]
    description: str


class PairEvidence(BaseModel):
    topic_id: str
    project: str
    level: EvidenceLevel
    reasons: list[EvidenceReason]


class WeightedRanking(BaseModel):
    weights: dict[str, float]
    normalization: str = "rank-percentile within compared candidates (0 = worst, 1 = best)"
    formula: str = "score = sum(weight_i * percentile_i) / sum(weight_i)"
    note: str = "Score reflects the user's stated preferences, not an objective truth."
    percentiles: dict[str, dict[str, float]]
    scores: dict[str, float]
    order: list[str]


class Comparison(BaseModel):
    axes: dict[str, str]
    candidates: list[str]
    excluded: dict[str, str] = Field(default_factory=dict)
    pareto_front: list[str] = Field(default_factory=list)
    dominated_by: dict[str, list[str]] = Field(default_factory=dict)
    weighted: WeightedRanking | None = None


class PairLabel(BaseModel):
    topic_id: str
    project: str
    label: LabelName
    rule_id: str


class PairRationale(BaseModel):
    topic_id: str
    project: str
    sentences: list[str]


class CacheInfo(BaseModel):
    mode: Literal["normal", "refresh", "disabled"]
    cache_dir: str | None
    hits: int = 0
    fetched: int = 0
    http_requests: int = 0
    oldest_observation_fetched_at: str | None = None


class AnalysisResult(BaseModel):
    schema_version: str
    tool_version: str
    methodology_version: str
    run_id: str
    parent_run_id: str | None = None
    request_version: int = 1
    created_at: str
    request: dict[str, Any]
    scope: Scope
    series: list[PairSeries]
    metrics: list[PairMetrics]
    evidence: list[PairEvidence]
    comparison: Comparison
    labels: list[PairLabel]
    rationale: list[PairRationale]
    warnings: list[Issue]
    cache: CacheInfo
    limitations: list[str]

    def metric(self, topic_id: str, project: str) -> PairMetrics:
        return next(m for m in self.metrics if m.topic_id == topic_id and m.project == project)
