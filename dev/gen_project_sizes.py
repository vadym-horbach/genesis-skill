"""Regenerate assets/project_sizes.json: open Wikipedia editions and their 12-month user views.

Used to validate language codes and to pick the default top-N languages (D17) without one
`aggregate` call per sitelink at analysis time. Run before each release:

    PYTHONPATH=src python dev/gen_project_sizes.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from interest_signals.analysis.periods import add_months, last_complete_month, month_range
from interest_signals.cache.store import CacheStore
from interest_signals.providers.wikipedia.aqs import Aqs
from interest_signals.providers.wikipedia.client import HttpClient

OUT = Path(__file__).resolve().parent.parent / "assets" / "project_sizes.json"


def main() -> int:
    client = HttpClient()
    data = client.get_json(
        "https://meta.wikimedia.org/w/api.php",
        {"action": "sitematrix", "smtype": "language", "format": "json",
         "smsiteprop": "url|code|closed", "smlangprop": "code|site"},
    )
    projects: list[tuple[str, str]] = []
    for key, entry in data["sitematrix"].items():
        if key == "count" or not isinstance(entry, dict):
            continue
        for site in entry.get("site", []):
            if site.get("code") == "wiki" and "closed" not in site:
                host = site["url"].removeprefix("https://").removesuffix(".org")
                projects.append((host.split(".")[0], host))
    end = last_complete_month()
    months = month_range(add_months(end, -11), end)
    aqs = Aqs(client, CacheStore(mode="disabled"))

    def size(item: tuple[str, str]) -> tuple[str, str, float]:
        lang, project = item
        values = aqs.project_views(project, months)
        return lang, project, sum(v for v, _ in values.values())

    rows = client.map(size, projects)
    rows.sort(key=lambda r: -r[2])
    payload = {
        "generated_for_months": [months[0], months[-1]],
        "projects": {lang: {"project": project, "views_12m": int(views)} for lang, project, views in rows},
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=1, ensure_ascii=False))
    print(f"wrote {len(rows)} projects to {OUT}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
