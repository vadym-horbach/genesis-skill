"""Provider contract. Wikipedia is the first implementation; others (Google Trends, YouTube, ...)
must return the same technical shapes but keep their own units, normalization and checks."""

from __future__ import annotations

from typing import Protocol

from interest_signals.models.errors import Issue
from interest_signals.models.request import AnalysisRequest, TopicSpec
from interest_signals.models.result import PairSeries, Period, SourceUse, TopicCandidates


class Provider(Protocol):
    name: str
    unit: str
    normalization: str

    def resolve(self, topic: TopicSpec, languages: list[str]) -> object | TopicCandidates:
        """Topic -> provider-specific cluster, or candidates when the topic is ambiguous."""

    def fetch(self, request: AnalysisRequest, resolutions: list, period: Period) -> list[PairSeries]:
        """Cluster -> monthly series per (topic, dimension value) with month statuses."""

    def validate(self) -> list[Issue]:
        """Quality warnings and provenance problems collected during resolve/fetch."""

    def sources(self) -> list[SourceUse]:
        """Which endpoints were used, how often, and how much came from cache."""
