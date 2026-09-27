# interest-signals

Agent Skill that measures attention to topics across Wikipedia language editions and, on request, writes a one-page HTML/PDF report with the agent's analysis in the user's language. Built for B2C teams deciding which topic, course or localization to validate next.

Example: *"Compare interest in intermittent fasting in Polish and Czech Wikipedia over the last two years."* The agent runs one command. It gets back scale, relative attention, year-over-year growth, a robust long-term trend, consistency, spikes, an evidence level, a label and template rationale, with every number computed by code.

## Install

Any agent supporting Agent Skills (Claude Code, Codex, Cursor, ...):

```sh
npx skills add vadym-horbach/interest-signals
```

`npx skills add` copies the whole skill folder (`src/`, `scripts/`, `assets/`, `references/`). From a local path it also copies untracked files such as `.venv`; install from the GitHub repo for a clean copy.

Or Claude Code directly:

```sh
git clone https://github.com/vadym-horbach/interest-signals ~/.claude/skills/interest-signals
```

Requirements: Python 3.12+ and network access. The first run creates `.venv` inside the skill directory from `requirements.lock` (hash-pinned). It uses only the stdlib `venv` module and pip. On systems without pip (Debian/Ubuntu without `python3-venv`) it downloads the official pip zipapp and checks its sha256. Nothing is installed outside the skill directory. To prepare the environment ahead of time, run `python3 scripts/setup.py`.

Optional environment variables:

| Variable | Purpose |
|---|---|
| `INTEREST_SIGNALS_CONTACT` | email/URL added to the User-Agent (recommended by Wikimedia) |
| `INTEREST_SIGNALS_CACHE_DIR` | cache and run state location (default: OS user cache dir) |

## Use without an agent

```sh
python3 scripts/analyze.py --topic "astronomy" --languages uk --months 24
python3 scripts/analyze.py --parent <run_id> --add-languages de
python3 scripts/analyze.py report-template <run_id>          # report content to fill/translate
python3 scripts/analyze.py --render <run_id> --content c.json --format pdf
python3 scripts/analyze.py cache status
```

An analysis writes no files. Its pinned request and canonical result (`AnalysisResult`) go to the `runs` table of the cache database (`cache.sqlite`, kept 30 days) for follow-ups and rendering. Reports are written only by `--render`, into the current directory or `--out DIR`, as `interest-signals-<topics>-<id>.html/.pdf`. `--content` adds the agent's analysis and the report language; every number in it must come from the result, or the render is rejected. Without `--content` the report is English with no analysis section.

## Layout

```text
SKILL.md                 agent instructions
scripts/analyze.py       stdlib bootstrap + single entry point
scripts/setup.py         optional environment pre-warm
src/interest_signals/    package: providers/, analysis/, pipeline/, cache/, output/
assets/                  report template, language edition sizes
references/              methodology.md, output-schema.md (generated)
tests/                   unit, synthetic, replay integration (+ live, opt-in)
eval/                    cheap-model end-to-end evaluation
dev/                     lock, schema, fixtures, project-size generators
```

## Development

```sh
python3 -m venv .venv-dev && . .venv-dev/bin/activate
pip install --require-hashes --no-deps -r requirements.lock
pip install pytest ruff pip-tools
pytest                                   # unit + synthetic + replay (no network)
pytest -m live                           # real Wikimedia APIs
ruff check src tests scripts dev eval
PYTHONPATH=src python dev/gen_schema.py  # after model changes
sh dev/lock.sh                           # after dependency changes (pip-compile --generate-hashes)
```

Methodology: `references/methodology.md`. Output contract: `references/output-schema.md`.

## Limitations

- Pageviews show attention to the selected articles. They do not measure demand or willingness to pay.
- Language edition is not the reader's country; country-level analysis is not supported.
- Merges and splits of articles are detected only approximately.
