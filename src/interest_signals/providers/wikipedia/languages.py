"""Wikipedia language editions: code validation and default language choice (D17)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from interest_signals import config
from interest_signals.models.errors import Code, Issue, warning

SIZES_FILE = Path(__file__).resolve().parents[4] / "assets" / "project_sizes.json"


@lru_cache(maxsize=1)
def project_sizes() -> dict[str, int]:
    data = json.loads(SIZES_FILE.read_text())
    return {lang: entry["views_12m"] for lang, entry in data["projects"].items()}


def project_for(language: str) -> str:
    return f"{language}.wikipedia"


def language_of(project: str) -> str:
    return project.split(".")[0]


def unsupported_language_issue(code: str) -> Issue:
    suggestion = config.LANGUAGE_CODE_HINTS.get(code)
    hint = (
        f"Did you mean '{suggestion}'? Use Wikipedia language codes (the subdomain of "
        f"<code>.wikipedia.org). Fix the request and rerun."
        if suggestion
        else "Use a Wikipedia language code, the subdomain of <code>.wikipedia.org "
        "(for example 'pl', 'cs', 'uk', 'de')."
    )
    return warning(
        Code.UNSUPPORTED_LANGUAGE,
        f"'{code}' is not an open Wikipedia language edition.",
        hint,
        language=code,
        suggestion=suggestion,
    )


def split_languages(codes: list[str]) -> tuple[list[str], list[Issue]]:
    known = project_sizes()
    valid = [c for c in codes if c in known]
    issues = [unsupported_language_issue(c) for c in codes if c not in known]
    return valid, issues


def top_languages(candidates: set[str], n: int = config.DEFAULT_LANGUAGE_COUNT) -> list[str]:
    sizes = project_sizes()
    ranked = sorted((c for c in candidates if c in sizes), key=lambda c: -sizes[c])
    return ranked[:n]
