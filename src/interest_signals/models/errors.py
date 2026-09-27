"""Structured issues: the agent-facing error/warning contract (D46, D47)."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class Code(StrEnum):
    # fatal
    INVALID_REQUEST = "INVALID_REQUEST"
    TOPIC_NOT_FOUND = "TOPIC_NOT_FOUND"
    EMPTY_CLUSTER = "EMPTY_CLUSTER"
    CLUSTER_TOO_LARGE = "CLUSTER_TOO_LARGE"
    TOO_MANY_TOPICS = "TOO_MANY_TOPICS"
    API_UNAVAILABLE = "API_UNAVAILABLE"
    RUN_NOT_FOUND = "RUN_NOT_FOUND"
    RUNTIME_UNSUPPORTED_PYTHON = "RUNTIME_UNSUPPORTED_PYTHON"
    DEPENDENCY_INSTALL_FAILED = "DEPENDENCY_INSTALL_FAILED"
    PYTHON_VENV_UNAVAILABLE = "PYTHON_VENV_UNAVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    # needs confirmation
    AMBIGUOUS_TOPIC = "AMBIGUOUS_TOPIC"
    # fatal or warning depending on context
    UNSUPPORTED_LANGUAGE = "UNSUPPORTED_LANGUAGE"
    UNSUPPORTED_DIMENSION = "UNSUPPORTED_DIMENSION"
    # warnings
    PARTIAL_DATA = "PARTIAL_DATA"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    PAGE_CREATED_DURING_PERIOD = "PAGE_CREATED_DURING_PERIOD"
    PAGE_MOVED_DURING_PERIOD = "PAGE_MOVED_DURING_PERIOD"
    PAGE_HISTORY_CHANGED = "PAGE_HISTORY_CHANGED"
    RESOLUTION_LOW_CONFIDENCE = "RESOLUTION_LOW_CONFIDENCE"
    CLUSTER_AUTO_SELECTED = "CLUSTER_AUTO_SELECTED"
    LANGUAGE_COVERAGE_LIMITED = "LANGUAGE_COVERAGE_LIMITED"
    LANGUAGE_NOT_COVERED = "LANGUAGE_NOT_COVERED"
    CLUSTER_COVERAGE_INCOMPLETE = "CLUSTER_COVERAGE_INCOMPLETE"
    CLUSTER_DOMINATED_BY_ENTITY = "CLUSTER_DOMINATED_BY_ENTITY"
    REDIRECTS_TRUNCATED = "REDIRECTS_TRUNCATED"
    PARTIAL_SEASONAL_CYCLE = "PARTIAL_SEASONAL_CYCLE"
    UA_CONTACT_MISSING = "UA_CONTACT_MISSING"


Severity = Literal["error", "warning"]


class Issue(BaseModel):
    code: Code
    severity: Severity
    message: str
    hint: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)


def warning(code: Code, message: str, hint: str | None = None, **context: Any) -> Issue:
    return Issue(code=code, severity="warning", message=message, hint=hint, context=context)


def error(code: Code, message: str, hint: str | None = None, **context: Any) -> Issue:
    return Issue(code=code, severity="error", message=message, hint=hint, context=context)


class FatalError(Exception):
    """Stops the pipeline; carries one or more error issues for the envelope."""

    def __init__(self, *issues: Issue):
        super().__init__("; ".join(i.message for i in issues))
        self.issues = list(issues)


class NeedsConfirmation(Exception):
    """Topic resolution could not pick a cluster deterministically."""

    def __init__(self, issues: list[Issue], candidates: list[dict[str, Any]]):
        super().__init__("topic needs confirmation")
        self.issues = issues
        self.candidates = candidates


class IssueLog:
    """Collects warnings, de-duplicating identical ones."""

    def __init__(self) -> None:
        self._items: list[Issue] = []
        self._seen: set[str] = set()

    def add(self, issue: Issue) -> None:
        key = issue.model_dump_json()
        if key not in self._seen:
            self._seen.add(key)
            self._items.append(issue)

    def warn(self, code: Code, message: str, hint: str | None = None, **context: Any) -> None:
        self.add(warning(code, message, hint, **context))

    def extend(self, issues: list[Issue]) -> None:
        for issue in issues:
            self.add(issue)

    @property
    def items(self) -> list[Issue]:
        return list(self._items)

    def codes(self) -> set[Code]:
        return {i.code for i in self._items}
