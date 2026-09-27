"""Page lifecycle checks (D34). Pure functions over already fetched data."""

from __future__ import annotations

from interest_signals import config


def creation_month(timestamp: str | None) -> str | None:
    return timestamp[:7] if timestamp else None


def history_change_months(
    months: list[str], net_bytes: dict[str, tuple[float, bool]], length: int | None
) -> list[str]:
    """Months whose net byte change exceeds HISTORY_BYTES_SHARE of the current page length: a
    content merge, split or rewrite. Net change ignores vandalism that was reverted."""
    if not length:
        return []
    limit = config.HISTORY_BYTES_SHARE * length
    return [m for m in months if abs(net_bytes.get(m, (0.0, False))[0]) > limit]


def likely_old_titles(
    title_views: dict[str, dict[str, tuple[float, bool]]], canonical: str, months: list[str]
) -> list[str]:
    """Redirect titles that carried most of the page's views in some month: typical of a title
    used before a move. Only these are checked against the move log (cheap, bounded)."""
    out: list[str] = []
    for title, values in title_views.items():
        if title == canonical:
            continue
        for m in months:
            total = sum(v.get(m, (0.0, False))[0] for v in title_views.values())
            if total > 0 and values.get(m, (0.0, False))[0] / total > config.MOVE_REDIRECT_SHARE:
                out.append(title)
                break
    return out
