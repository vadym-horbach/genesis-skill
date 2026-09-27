"""AnalysisRequest: what the agent asks for (D11, D16, D17, D23)."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from interest_signals import config

QID_RE = re.compile(r"^Q[1-9][0-9]*$")
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
LANG_RE = re.compile(r"^[a-z][a-z0-9-]{1,15}$")


class TitleRef(BaseModel):
    language: str
    title: str

    @field_validator("language")
    @classmethod
    def _lang(cls, v: str) -> str:
        return v.strip().lower()


class TopicSpec(BaseModel):
    """One topic. Explicit `qids` or `titles` win over `query`; `query` then only labels the topic."""

    topic_id: str | None = None
    query: str | None = None
    qids: list[str] = Field(default_factory=list)
    titles: list[TitleRef] = Field(default_factory=list)

    @field_validator("qids")
    @classmethod
    def _qids(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for q in v:
            q = q.strip().upper()
            if not QID_RE.match(q):
                raise ValueError(f"invalid Wikidata id {q!r}; expected like 'Q42'")
            if q not in out:
                out.append(q)
        return out

    @model_validator(mode="after")
    def _one_source(self) -> TopicSpec:
        if not (self.query and self.query.strip()) and not self.qids and not self.titles:
            raise ValueError("each topic needs `query`, `qids` or `titles`")
        return self

    @property
    def label(self) -> str:
        if self.query:
            return self.query
        if self.qids:
            return ", ".join(self.qids)
        return ", ".join(f"{t.language}:{t.title}" for t in self.titles)


class Criteria(BaseModel):
    weights: dict[str, float] | None = None

    @field_validator("weights")
    @classmethod
    def _weights(cls, v: dict[str, float] | None) -> dict[str, float] | None:
        if v is None:
            return None
        unknown = set(v) - set(config.AXES)
        if unknown:
            raise ValueError(f"unknown weight axes {sorted(unknown)}; allowed: {sorted(config.AXES)}")
        if any(w < 0 for w in v.values()):
            raise ValueError("weights must be >= 0")
        if not any(w > 0 for w in v.values()):
            raise ValueError("at least one weight must be > 0")
        return v


class AnalysisRequest(BaseModel):
    topics: list[TopicSpec] = Field(min_length=1)
    languages: list[str] = Field(default_factory=list)
    months: int = Field(default=config.DEFAULT_MONTHS, ge=1, le=config.MAX_MONTHS)
    end_month: str | None = None
    dimensions: list[Literal["language", "country"]] = Field(default_factory=lambda: ["language"])
    countries: list[str] = Field(default_factory=list)
    criteria: Criteria | None = None

    @field_validator("languages")
    @classmethod
    def _languages(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for code in v:
            code = code.strip().lower()
            if not LANG_RE.match(code):
                raise ValueError(f"invalid language code {code!r}")
            if code not in out:
                out.append(code)
        return out

    @field_validator("end_month")
    @classmethod
    def _end_month(cls, v: str | None) -> str | None:
        if v is not None and not MONTH_RE.match(v):
            raise ValueError("end_month must be YYYY-MM")
        return v

    @model_validator(mode="after")
    def _topic_ids(self) -> AnalysisRequest:
        seen: set[str] = set()
        for i, topic in enumerate(self.topics, start=1):
            if not topic.topic_id:
                topic.topic_id = f"t{i}"
            if topic.topic_id in seen:
                raise ValueError(f"duplicate topic_id {topic.topic_id!r}")
            seen.add(topic.topic_id)
        if self.countries and "country" not in self.dimensions:
            self.dimensions = [*self.dimensions, "country"]
        return self
