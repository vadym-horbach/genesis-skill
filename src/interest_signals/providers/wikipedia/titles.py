"""One de-duplicated set of titles per page, built before any AQS request (D19).

AQS counts views per exact title and does not follow redirects. A page's attention is therefore
the sum over its canonical title, its redirects and titles it had before a move. After a move the
old title usually becomes a redirect, so the set must be de-duplicated to avoid double counting.
"""

from __future__ import annotations

from difflib import SequenceMatcher

from interest_signals import config
from interest_signals.providers.wikipedia.mediawiki import normalize_title


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize_title(a).casefold(), normalize_title(b).casefold()).ratio()


def build_title_set(
    canonical: str,
    redirects: list[str],
    old_titles: list[str] | None = None,
    cap: int = config.MAX_REDIRECTS_PER_PAGE,
) -> tuple[list[str], int]:
    """Return (titles, truncated_count). Canonical first, then old titles, then top redirects."""
    seen: set[str] = set()
    titles: list[str] = []

    def add(title: str) -> bool:
        key = normalize_title(title)
        if not key or key in seen:
            return False
        seen.add(key)
        titles.append(key)
        return True

    add(canonical)
    for title in old_titles or []:
        add(title)
    unique_redirects = []
    redirect_keys: set[str] = set()
    for r in redirects:
        key = normalize_title(r)
        if key and key not in seen and key not in redirect_keys:
            redirect_keys.add(key)
            unique_redirects.append(key)
    ranked = sorted(unique_redirects, key=lambda r: (-similarity(r, canonical), r))
    for title in ranked[:cap]:
        add(title)
    return titles, max(0, len(ranked) - cap)
