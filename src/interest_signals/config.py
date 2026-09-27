"""Thresholds, limits and weights. Every value here is documented in references/methodology.md.

Changing a value requires updating methodology.md and the tests that pin it in the same commit.
"""

# Request limits
MAX_TOPICS = 3
MAX_ENTITIES_PER_CLUSTER = 5
DEFAULT_MONTHS = 24
MAX_MONTHS = 120
MIN_MONTHS_FOR_GROWTH = 15
EARLIEST_MONTH = "2015-07"
DEFAULT_LANGUAGE_COUNT = 10

# HTTP
REQUESTS_PER_MINUTE = 100
CONCURRENCY = 4
MAX_RETRIES = 5
TIMEOUT_SECONDS = 30.0
BATCH_SIZE = 50
REPO_URL = "https://github.com/vadym-horbach/interest-signals"

# Topic resolution (D13, D14)
SEARCH_LIMIT = 10
MAX_CANDIDATES = 8
SCORE_WEIGHTS = {"exact_match": 0.5, "title_similarity": 0.2, "search_rank": 0.2, "coverage": 0.1}
RANK_TEXT_FLOOR = 0.25  # search-rank weight kept when the hit shares no words with the query
AUTO_SELECT_SECOND_RATIO = 0.5
MAX_REDIRECTS_PER_PAGE = 20

# Cluster (D21)
DOMINANCE_SHARE = 0.8

# Series and metrics (D24-D32)
RECENT_MONTHS = 3
MAX_ZERO_SHARE = 0.10
CONSISTENCY_WINDOW = 12
MIN_CONSISTENCY_WINDOWS = 4
MIN_POINTS_PER_WINDOW = 10
SPIKE_ROLLING_WINDOW = 5
SPIKE_Z = 3.5
SPIKE_MIN_LOG_RESIDUAL = 0.405  # ln(1.5): a spike is at least 50% above its local median

# Evidence (D33)
EVIDENCE_HIGH_MIN_MONTHS = 24
EVIDENCE_LOW_MAX_UNAVAILABLE = 2
EVIDENCE_HIGH_MIN_CONSISTENCY = 0.7
EVIDENCE_HIGH_MAX_SPIKES = 1
EVIDENCE_LOW_TOP2_SHARE = 0.4

# Lifecycle (D34)
HISTORY_BYTES_SHARE = 0.5  # |net byte change| in a month vs current page length
MOVE_REDIRECT_SHARE = 0.5

# Labels (D37) and evidence sign checks: changes within +-FLAT_BAND count as flat
LABEL_MIN_CONSISTENCY = 0.5
FLAT_BAND = 0.05

# Cache (D40)
IMMUTABLE_AFTER_DAYS = 3
RECENT_MONTH_TTL_HOURS = 24
METADATA_TTL_DAYS = 7
CACHE_SCHEMA_VERSION = 2
RUN_RETENTION_DAYS = 30
RESOLVER_VERSION = 1

# Comparison axes: request weight name -> metric field
AXES = {
    "scale": "recent_views",
    "relative_attention": "recent_per_million",
    "growth": "yoy_normalized",
    "consistency": "positive_window_share",
}

# Frequent wrong language codes -> Wikipedia code (hint only, never auto-corrected)
LANGUAGE_CODE_HINTS = {
    "cz": "cs", "ua": "uk", "jp": "ja", "gr": "el", "dk": "da", "se": "sv", "kr": "ko",
    "cn": "zh", "by": "be", "rs": "sr", "ee": "et", "ge": "ka", "il": "he", "vn": "vi",
    "br": "pt", "us": "en", "gb": "en", "uk-ua": "uk", "pl-pl": "pl",
}

# Report content written by the agent (caps keep the PDF on one page)
REPORT_HEADLINE_MAX = 160
REPORT_FINDINGS_MAX = 4
REPORT_FINDING_MAX = 280
REPORT_RECOMMENDATION_MAX = 400
REPORT_NEXT_STEPS_MAX = 3
REPORT_NEXT_STEP_MAX = 160
REPORT_FREE_SMALL_NUMBER = 12  # integers up to this are counts (months, languages) and need no source
