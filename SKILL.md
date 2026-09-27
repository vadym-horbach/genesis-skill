---
name: interest-signals
description: Measures attention to topics in Wikipedia language editions (pageviews, growth, trend, evidence quality) and, on request, writes a one-page HTML/PDF report with your analysis in the user's language. Use when a user asks whether interest in a topic is growing, compares topics or languages for a B2C product (which course, which localization, which audience to validate next), or wants a shareable report from Wikipedia pageview data. Also handles follow-ups on a previous run (add a language, change the period, add a topic, change criteria, write or rewrite the report).
allowed-tools: Bash(python3 */scripts/analyze.py *) Bash(python */scripts/analyze.py *)
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
- `--request FILE` takes the same fields as JSON (schema: `references/output-schema.md`).

The analysis writes no files; run state stays in the skill cache for follow-ups.

Stdout is exactly one JSON envelope. Exit code: 0 `ok`, 2 `needs_confirmation`, 1 `error`.

## Read the envelope

**`ok`**: answer in chat from `summary`:

1. `summary.topics[].cluster`: which articles were analyzed. If `auto_selected` is true, name the article so the user can correct it.
2. `summary.per_topic_language[]`: one row per topic and language edition, with `label`, `evidence` and `rationale`. Retell the `rationale` sentences; they already contain the right numbers.
3. `warnings[]`: mention each one that changes the conclusion (history changes, missing articles, short history, spikes). Use its `hint`.

Write a report only when the user asks for one (see Report).

**`needs_confirmation`** (`AMBIGUOUS_TOPIC`): the topic matched several articles. Show `candidates[].candidates[]` (label, description, relation_hint) and ask the user which ones belong to the topic (one or several, max 5). Rerun with `--qids` of the chosen items. Pick only with the user's answer.

**`error`**: read `errors[0].hint` and act on it (fix the language code, shorten the request, retry later). Report `INTERNAL_ERROR` to the user without retrying.

## Labels and wording

Labels come from fixed rules: `candidate for further validation`, `monitor`, `weaker signal`, `insufficient evidence`. Evidence is `high` / `medium` / `low` from explicit rules (`references/methodology.md`); it is not a probability.

Recommend in the same vocabulary: "a candidate for further validation", "a stronger signal than", "investigate next", "monitor", "insufficient evidence". Always add that the signal needs validation with real market data.

## Follow-ups

Each run prints `summary.run_id`. For a follow-up, pass `--parent <run_id>` plus only what changes; cached raw data is reused and metrics are recomputed:

| User says | Command |
|---|---|
| "Add German" | `--parent <id> --add-languages de` |
| "Only the last 12 months" | `--parent <id> --months 12` |
| "Growth matters more than scale" | `--parent <id> --weights growth=2,scale=1` |
| "Compare with another topic" | `--parent <id> --add-topic "keto diet"` |
| "Prepare the report" | see Report |

## Report

Only on the user's request. The report carries **your analysis** in the **report language**: the language the user names for the report, otherwise the language of the user's messages.

1. `python3 <skill>/scripts/analyze.py report-template <run_id>` prints `summary.report_template`: the report content prefilled in English.
2. Write the content:
   - `language`: tag of the report language (`en`, `uk`, `de`, ...).
   - `analysis`: `headline` (one sentence), `findings` (1-4 sentences comparing topics and editions), `recommendation` (what to validate next, in the label vocabulary, with the market-data caveat), `next_steps` (0-3). Every number comes from the envelope `summary`; rounding to thousands or millions is fine, new arithmetic (ratios, sums) is rejected.
   - Report language other than English: translate every value of `text` (keep `{placeholders}`), `topics`, `entities`, `warnings`, `limitations`, and optionally `details`. English: send only `language` and `analysis`.
3. Render into the user's directory. Pass the content as one single-quoted JSON argument on one line; write apostrophes inside it as `’`:

```bash
python3 <skill>/scripts/analyze.py --render <run_id> --content-json '{"language": "en", "analysis": {"headline": "...", "findings": ["..."], "recommendation": "...", "next_steps": []}}'
```

`--format pdf` or `--format html` limits the formats (default both); `--out DIR` when the user names a folder. Give the user `summary.artifacts.report_pdf` / `report_html`.

- `REPORT_CONTENT_INVALID`: the listed numbers are not in the result, or a field is too long; fix them and render again.
- `REPORT_UNTRANSLATED`: translate the listed entries and render again.
- `REPORT_PDF_GLYPHS_MISSING`: give the user the HTML report.

Rendering again without content reuses the last content of that run (for example, PDF only).

## Limits

- Language edition is not country: Poles read English articles too.
- A missing article in a language is not missing interest.
- Cache: `analyze.py cache status` / `cache clear` (also deletes run state); `--refresh` refetches, `--no-cache` bypasses cached data.
