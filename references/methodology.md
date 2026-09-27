# Methodology (v1.0)

How `interest-signals` turns Wikipedia pageviews into comparable signals. All thresholds live in `src/interest_signals/config.py`; this document and the tests pin them.

## 1. What is measured

- **Unit**: monthly pageviews from the Wikimedia Analytics API (AQS), `agent=user` (human traffic; automated and spider traffic excluded), `access=all-access`.
- **Meaning**: attention to a selected set of articles. It is not total demand for a topic, not unique people (one reader can open several articles), and not willingness to pay, market size, competition, CAC, conversion or product-market fit.
- **Language, not country**: a language edition is not a country. Country-level analysis is not supported: AQS has no per-article breakdown by country (only project-level buckets and daily top lists). A missing article does not mean missing interest.
- **Only numbers from AQS enter metrics.** MediaWiki Action API and Wikidata supply metadata only: search, redirects, page ids, creation date, move log, language links.

## 2. Period

Complete calendar months only. "Last 24 months" on 2026-09-27 means 2024-09 to 2026-08. The result stores `from`, `to`, `months`. Maximum 120 months; data starts 2015-07.

## 3. Topic resolution and article cluster

A topic is a **cluster** of 1 to 5 Wikidata entities (max 3 topics per request). Each entity brings all its Wikipedia language versions through Wikidata sitelinks; titles are never translated.

Free-text resolution is deterministic:

1. Search `en.wikipedia` plus every requested edition; exclude disambiguation pages.
2. Check whether the query itself is a page title or redirect (exact match).
3. Score each candidate: `0.5 exact + 0.2 title similarity + 0.2 search rank + 0.1 coverage`.
   - Search rank is `1 / rank`, counted among hits that share words with the query (by 5-letter prefix). Hits sharing no words keep 25% of the rank weight.
   - Coverage is the share of requested languages where the entity has an article.
4. **Auto-select** only if all hold: exact title or redirect match; first relevant search hit; not a disambiguation page; runner-up score below 50% of the top. The run then warns `CLUSTER_AUTO_SELECTED`.
5. Otherwise return `needs_confirmation` with up to 8 candidates (label, description, extract, relation hints). Alternative meanings never merge into a cluster automatically.

Explicit `qids` or titles skip search and are treated as chosen by the user.

**Pages and titles.** Entities are de-duplicated by QID, pages by `(project, page_id)`; a page without a QID is keyed `page:<project>:<page_id>`. AQS counts views per exact title and does not follow redirects, so each page's views are the sum over one de-duplicated set of titles: canonical title, titles found in the move log, and up to 20 redirects (ranked by similarity to the canonical title; `REDIRECTS_TRUNCATED` when cut). A pre-move title that became a redirect is counted once.

**Aggregation.** Raw monthly views are summed across the cluster's pages within one language edition. Metrics are computed from that aggregated series; growth or trends of individual articles are never averaged. Nothing is summed across language editions. Each entity's share of recent views is reported (`components[].recent_share`); a share above 80% raises `CLUSTER_DOMINATED_BY_ENTITY`. Editions where only part of the cluster exists raise `CLUSTER_COVERAGE_INCOMPLETE`.

**Languages.** Requested editions are used as given. Without a request, the 10 largest editions (12-month views, `assets/project_sizes.json`) with an article are used and `LANGUAGE_COVERAGE_LIMITED` is raised. `coverage` always lists every sitelink with status `fetched`, `not_requested` or `missing`.

## 4. Month status

| Status | Meaning | Used in metrics |
|---|---|---|
| `ok` | AQS returned views | yes |
| `zero_filled` | page existed, AQS returned no row (no views) | yes, as 0 |
| `not_existing` | before the page's first revision | no |
| `unavailable` | the request failed | no, never treated as 0 |

## 5. Metrics per (topic, language edition)

| Metric | Definition |
|---|---|
| Scale `recent_views` | median of the last 3 months of the period (null if any of them is invalid) |
| Relative attention `recent_per_million` | median of the last 3 months of `views / edition total views x 1e6` |
| YoY raw / normalized | `median(last 3 months) / median(same 3 months one year earlier) - 1`, on raw views and on per-million values |
| Long-term trend | Theil-Sen slope of `log(y + offset)` over month index; `annual_change = exp(12 x slope) - 1`; 95% CI from the same estimator (`trend_ci`) |
| Consistency `positive_window_share` | share of rolling 12-month windows (step 1, at least 10 valid points each, at least 4 windows) whose Theil-Sen slope is positive; computed on the normalized series |
| Spikes | months where the log value exceeds the centered 5-month rolling median by at least 50% and by robust z > 3.5 (`z = 0.6745 x (residual - median) / MAD`); raw series |
| `spike_ratio`, `top_2_month_share` | max / median; share of the two largest months in the total |
| Volatility | `1.4826 x MAD` of log residuals around the normalized Theil-Sen line |

Rules:

- **Minimum history.** YoY, trend and consistency need 15 valid months. Below that they are null with a reason, and the run warns `INSUFFICIENT_HISTORY`. Scale is still reported.
- **Log offset.** The offset is 0 when all values are positive, otherwise half the smallest positive value. With more than 10% zero months the trend is refused.
- **Why log.** Trends are multiplicative, so languages of very different size stay comparable.
- **Why normalize.** Edition totals change (for example, less human traffic, and reclassification of automated traffic). Normalized growth separates the topic from the whole edition. Raw and normalized growth are reported separately.
- **Seasonality.** YoY compares the same calendar months, so seasonality cancels there. Twelve-month consistency windows each contain a full cycle. Theil-Sen over a period that is not a whole number of years can carry seasonal bias, and `PARTIAL_SEASONAL_CYCLE` warns about it. Seasonal decomposition is not implemented.
- **Flat band.** Changes within ±5% (`FLAT_BAND`) count as flat for sign checks and labels.

## 6. Evidence quality

Evidence is a rule table, not a probability. Statistical uncertainty is reported separately as the trend's 95% CI.

**low**, if any of these holds:

| Rule | Condition |
|---|---|
| L1 | fewer than 15 months |
| L2 | more than 2 unavailable months |
| L3 | normalized YoY and trend point in opposite directions, beyond the flat band |
| L4 | two months hold more than 40% of all views |
| L5 | topic resolution has low confidence |
| L6 | normalized YoY or trend could not be computed |

**high**, if none of the above holds and all of these hold (otherwise **medium**; failed rules are listed in `reasons`):

| Rule | Condition |
|---|---|
| H1 | at least 24 months |
| H2 | no unavailable months |
| H3 | YoY and trend have the same direction |
| H4 | direction holds in at least 70% of windows (rising at least 0.7 or falling at most 0.3) |
| H5 | at most 1 spike |
| H6 | no page lifecycle warning |

## 7. Page lifecycle

| Warning | Detection |
|---|---|
| `PAGE_CREATED_DURING_PERIOD` | first revision inside the period; earlier months are `not_existing` |
| `PAGE_MOVED_DURING_PERIOD` | a redirect title carried more than 50% of the page's views in some month, and the move log shows it moved to the page within the period. Its views are already in the title set, so history is not lost. |
| `PAGE_HISTORY_CHANGED` | a month whose net byte change (AQS `bytes-difference/net`) exceeds 50% of the current page length. This is a proxy for merge, split or rewrite. Net rather than absolute change, so reverted vandalism cancels out. |

**Limitation.** Merges and splits are detected only approximately. Moves are checked only for redirects that carried most of the traffic, which keeps API calls bounded.

## 8. Comparison and labels

Candidates are `(topic, language edition)` pairs.

- **Default comparison.** The Pareto front on scale, relative attention, normalized YoY and consistency. Pairs with low evidence or missing axes are excluded and the reason is listed. No weighted score is produced by default.
- **Weighted ranking.** Only when the user gives weights. Each axis becomes a rank percentile within the compared pairs (0 is worst, 1 is best; ties are averaged). `score = sum(w x percentile) / sum(w)`. The weights, percentiles and formula are stored. The score reflects the user's preferences, not an objective truth.

Labels are an ordered, first-match table:

| Rule | Label | Condition |
|---|---|---|
| R1 | `insufficient evidence` | evidence low, or growth or trend missing |
| R2 | `candidate for further validation` | on the Pareto front, normalized YoY above 5%, trend above 5%, consistency at least 0.5 |
| R3 | `monitor` | normalized YoY or trend above 5% |
| R4 | `weaker signal` | everything else |

`rationale` sentences are filled from these fields by templates, so the agent retells numbers instead of inventing them.

## 9. Cache

SQLite in the user cache directory (`INTEREST_SIGNALS_CACHE_DIR` overrides it), outside the skill source tree. Only raw observations and metadata are stored; metrics, rankings, labels, charts and reports are always recomputed.

- **Granularity.** One row per `(kind, project, title, month)`. A wider follow-up downloads only the missing months and titles.
- **Freshness.**
  - A month is immutable once it ended more than 3 days before it was fetched; younger months expire after 24 hours.
  - Metadata (search results, pages, redirects, sitelinks, creation dates, moves) expires after 7 days.
- **Controls.**
  - A schema version change clears the cache.
  - `--refresh` ignores cached data.
  - `--no-cache` uses memory only.
  - `cache status` and `cache clear` inspect and delete it.
