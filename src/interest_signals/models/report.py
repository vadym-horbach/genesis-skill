"""ReportContent: what the agent adds to a report (its analysis, the report language and the
translated interface text). Numbers still come from the result; see output/grounding.py."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

from interest_signals import config

LANG_TAG_RE = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$")


class ReportAnalysis(BaseModel):
    """The agent's conclusions, written in the report language from the run's numbers."""

    headline: str = Field(min_length=1, max_length=config.REPORT_HEADLINE_MAX)
    findings: list[str] = Field(min_length=1, max_length=config.REPORT_FINDINGS_MAX)
    recommendation: str = Field(min_length=1, max_length=config.REPORT_RECOMMENDATION_MAX)
    next_steps: list[str] = Field(default_factory=list, max_length=config.REPORT_NEXT_STEPS_MAX)

    @field_validator("findings")
    @classmethod
    def _findings(cls, v: list[str]) -> list[str]:
        for item in v:
            if not item.strip() or len(item) > config.REPORT_FINDING_MAX:
                raise ValueError(f"each finding needs 1-{config.REPORT_FINDING_MAX} characters")
        return v

    @field_validator("next_steps")
    @classmethod
    def _next_steps(cls, v: list[str]) -> list[str]:
        for item in v:
            if not item.strip() or len(item) > config.REPORT_NEXT_STEP_MAX:
                raise ValueError(f"each next step needs 1-{config.REPORT_NEXT_STEP_MAX} characters")
        return v


class ReportContent(BaseModel):
    """`--content` for `--render`. Only `language` and `analysis` are needed for English; for
    another language, translate every entry of the `report-template` output as well."""

    language: str = "en"
    analysis: ReportAnalysis | None = None
    text: dict[str, str] = Field(default_factory=dict, description="Interface text by key.")
    topics: dict[str, str] = Field(default_factory=dict, description="topic_id -> display name.")
    entities: dict[str, str] = Field(default_factory=dict, description="Entity key (QID) -> label.")
    details: dict[str, str] = Field(default_factory=dict, description="Pair key -> explanation.")
    warnings: list[str] | None = Field(default=None, description="Warning messages, report order.")
    limitations: list[str] | None = None

    @field_validator("language")
    @classmethod
    def _language(cls, v: str) -> str:
        v = v.strip()
        if not LANG_TAG_RE.match(v):
            raise ValueError(f"invalid language tag {v!r}; expected like 'en', 'uk', 'pt-BR'")
        return v

    @property
    def is_english(self) -> bool:
        return self.language.split("-")[0] == "en"
