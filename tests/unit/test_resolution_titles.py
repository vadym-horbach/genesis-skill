from __future__ import annotations

from interest_signals.models.result import PairSeries
from interest_signals.providers.wikipedia import lifecycle
from interest_signals.providers.wikipedia.provider import PageData, PageRef, build_pair_series
from interest_signals.providers.wikipedia.resolver import (
    _Cand,
    score_candidate,
    should_auto_select,
    text_match,
)
from interest_signals.providers.wikipedia.titles import build_title_set

MONTHS = ["2025-01", "2025-02", "2025-03"]


def cand(key, exact=True, rank=1, sim=1.0, cov=1.0, tm=1.0):
    c = _Cand(key=key, qid=key, best_rank=rank, exact=exact, title_similarity=sim, coverage=cov, text_match=tm)
    c.score = score_candidate(c)
    return c


def test_auto_select_all_conditions():
    top, second = cand("Q1"), cand("Q2", exact=False, rank=2, sim=0.5, cov=1.0)
    assert should_auto_select([top, second])
    assert should_auto_select([top])


def test_auto_select_each_condition_breaks_it():
    second = cand("Q2", exact=False, rank=2, sim=0.5)
    assert not should_auto_select([cand("Q1", exact=False), second])
    assert not should_auto_select([cand("Q1", rank=2), second])
    close = cand("Q2", exact=False, rank=2, sim=1.0, cov=1.0)
    close.score = 0.9
    assert not should_auto_select([cand("Q1"), close])
    assert not should_auto_select([])


def test_text_match_uses_word_prefixes():
    assert text_match("learning English", ["English learners", None]) == 1.0
    assert text_match("learning English", ["Gra edukacyjna", "rodzaj gry"]) == 0.0
    assert text_match("a b", ["x"]) == 1.0


def test_title_set_dedupes_moved_title_that_is_also_redirect():
    titles, truncated = build_title_set("New name", ["Old_name", "Other"], old_titles=["Old name"])
    assert titles == ["New name", "Old name", "Other"]
    assert truncated == 0


def test_title_set_caps_redirects_by_similarity():
    redirects = [f"Unrelated {i}" for i in range(30)] + ["Astronomy (science)"]
    titles, truncated = build_title_set("Astronomy", redirects, cap=5)
    assert titles[0] == "Astronomy" and "Astronomy (science)" in titles
    assert len(titles) == 6 and truncated == 26


def page(entity, pid, values, status):
    ref = PageRef(entity, "xx.wikipedia", pid, f"T{pid}", 1000, [f"T{pid}"])
    return PageData(ref, dict(zip(MONTHS, values)), set(), dict(zip(MONTHS, status)))


def test_cluster_aggregation_sums_raw_and_marks_statuses():
    a = page("Q1", 1, [100, 100, 100], ["ok", "ok", "ok"])
    b = page("Q2", 2, [0, 50, 30], ["not_existing", "ok", "zero_filled"])
    s: PairSeries = build_pair_series("t1", "xx.wikipedia", MONTHS, [a, b], {m: 1e6 for m in MONTHS})
    assert s.views == [100, 150, 130]
    assert s.per_million == [100, 150, 130]
    assert s.status == ["ok", "ok", "ok"]
    assert [round(c.recent_share, 3) for c in s.components] == [round(300 / 380, 3), round(80 / 380, 3)]


def test_cluster_unavailable_month_is_not_zero():
    a = page("Q1", 1, [100, 100, 100], ["ok", "unavailable", "ok"])
    s = build_pair_series("t1", "xx.wikipedia", MONTHS, [a], None)
    assert s.views[1] is None and s.status[1] == "unavailable"
    assert s.per_million == [None, None, None]


def test_history_change_months_uses_net_bytes():
    net = {"2025-01": (100.0, True), "2025-02": (-700.0, True), "2025-03": (0.0, True)}
    assert lifecycle.history_change_months(MONTHS, net, 1000) == ["2025-02"]
    assert lifecycle.history_change_months(MONTHS, net, None) == []


def test_likely_old_titles():
    views = {
        "New": {"2025-01": (0.0, False), "2025-02": (90.0, True)},
        "Old": {"2025-01": (100.0, True), "2025-02": (5.0, True)},
        "Typo": {"2025-01": (1.0, True), "2025-02": (1.0, True)},
    }
    assert lifecycle.likely_old_titles(views, "New", MONTHS[:2]) == ["Old"]


def test_dominance_warning_only_for_multi_article_clusters():
    from interest_signals.models.errors import IssueLog
    from interest_signals.pipeline.analyze import dominance_warnings

    broad = page("Q1", 1, [900, 900, 900], ["ok", "ok", "ok"])
    narrow = page("Q2", 2, [100, 100, 100], ["ok", "ok", "ok"])
    log = IssueLog()
    dominance_warnings([build_pair_series("t1", "xx.wikipedia", MONTHS, [broad, narrow], None)], log)
    assert [(i.code.value, i.context["entity"]) for i in log.items] == [("CLUSTER_DOMINATED_BY_ENTITY", "Q1")]
    log = IssueLog()
    dominance_warnings([build_pair_series("t1", "xx.wikipedia", MONTHS, [broad], None)], log)
    assert log.items == []
