"""The single JSON object printed to stdout (D46)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from interest_signals import __version__
from interest_signals.models.errors import Issue

Status = Literal["ok", "needs_confirmation", "error"]

EXIT_CODES: dict[str, int] = {"ok": 0, "error": 1, "needs_confirmation": 2}


class Envelope(BaseModel):
    status: Status
    tool_version: str = __version__
    summary: dict[str, Any] | None = None
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[Issue] = Field(default_factory=list)
    warnings: list[Issue] = Field(default_factory=list)

    @property
    def exit_code(self) -> int:
        return EXIT_CODES[self.status]
