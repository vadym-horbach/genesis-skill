---
name: interest-signals
description: Measures attention to topics in Wikipedia language editions (pageviews, growth, trend, evidence quality) and produces charts plus a one-page HTML/PDF report. Use when a user asks whether interest in a topic is growing, compares topics or languages for a B2C product (which course, which localization, which audience to validate next), or wants a shareable report from Wikipedia pageview data. Also handles follow-ups on a previous run (add a language, change the period, add a topic, change criteria, regenerate the report).
allowed-tools: Bash(python3 *scripts/analyze.py*) Bash(python *scripts/analyze.py*)
---

# interest-signals

You orchestrate and explain; the code computes. Every number you state comes from the tool's output. Pageviews are **attention to the selected articles**: a signal to pick what to validate next, never demand, market size or willingness to pay.

Name results by **language edition** ("Polish Wikipedia", "pl.wikipedia"), because readers of an edition live in many countries. For a question about countries, first state that country-level data is not available (Wikimedia publishes no per-article views by country). Then, only if useful, offer language editions as a different signal, run with `--country <CC>` added so the result records the limitation.

## Runtime

Python 3.12+ with network access. The first run creates `.venv` inside this skill directory (about a minute); nothing is installed outside it. If `python3 --version` fails or is older than 3.12, tell the user Python 3.12+ is required and stop.

## Run

One call runs the whole pipeline. Run from the user's working directory; `<skill>` is this directory.

```bash
python3 <skill>/scripts/analyze.py --topic "intermittent fasting" --languages pl cs --months 24
```

Flags:

- `--topic TEXT` one topic (repeat, max 3). `--qids Q1,Q2` one topic made of exact Wikidata items (max 5).
- `--languages pl cs uk` Wikipedia language codes (subdomain of `<code>.wikipedia.org`: `cs` not `cz`, `uk` not `ua`, `ja` not `jp`). Omit to get the 10 largest editions that have the article.
- `--months N` complete calendar months (default 24; growth needs 15 or more).
- `--weights growth=2,scale=1` only when the user states priorities. Axes: `scale`, `relative_attention`, `growth`, `consistency`.
- `--format html,pdf` (default both). `--request FILE` takes the same fields as JSON (schema: `references/output-schema.md`).

Stdout is exactly one JSON envelope. Exit code: 0 `ok`, 2 `needs_confirmation`, 1 `error`.

## Read the envelope

**`ok`**: answer from `summary`:

1. `summary.topics[].cluster`: which articles were analyzed. If `auto_selected` is true, name the article so the user can correct it.
2. `summary.per_topic_language[]`: one row per topic and language edition, with `label`, `evidence` and `rationale`. Retell the `rationale` sentences; they already contain the right numbers.
3. `warnings[]`: mention each one that changes the conclusion (history changes, missing articles, short history, spikes). Use its `hint`.
4. `summary.artifacts`: give the paths of `report_pdf` / `report_html` when the user wants a report.

**`needs_confirmation`** (`AMBIGUOUS_TOPIC`): the topic matched several articles. Show `candidates[].candidates[]` (label, description, relation_hint) and ask the user which ones belong to the topic (one or several, max 5). Rerun with `--qids` of the chosen items. Pick only with the user's answer.

**`error`**: read `errors[0].hint` and act on it (fix the language code, shorten the request, retry later). Report `INTERNAL_ERROR` to the user without retrying.

## Labels and wording

Labels come from fixed rules: `candidate for further validation`, `monitor`, `weaker signal`, `insufficient evidence`. Evidence is `high` / `medium` / `low` from explicit rules (`references/methodology.md`); it is not a probability.

Recommend in the same vocabulary: "a candidate for further validation", "a stronger signal than", "investigate next", "monitor", "insufficient evidence". Always add that the signal needs validation with real market data.

## Follow-ups

Each run prints `run_dir` and `summary.run_id`. For a follow-up, pass `--parent <run_id>` plus only what changes; cached raw data is reused and metrics are recomputed:

| User says | Command |
|---|---|
| "Add German" | `--parent <id> --add-languages de` |
| "Only the last 12 months" | `--parent <id> --months 12` |
| "Growth matters more than scale" | `--parent <id> --weights growth=2,scale=1` |
| "Compare with another topic" | `--parent <id> --add-topic "keto diet"` |
| "Prepare the report" (no data change) | `--render <id>` (add `--format pdf` for PDF only) |

Keep `--out` identical between a run and its follow-ups when you set it.

## Limits

- Language edition is not country: Poles read English articles too.
- A missing article in a language is not missing interest.
- Cache: `analyze.py cache status` / `cache clear`; `--refresh` refetches, `--no-cache` bypasses.
