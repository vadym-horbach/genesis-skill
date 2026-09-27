"""End-to-end runs of the CLI on recorded Wikimedia responses (no network)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from interest_signals import cli
from interest_signals.models.result import AnalysisResult


def run_cli(capsys, *args: str) -> tuple[int, dict]:
    code = cli.main(list(args))
    return code, json.loads(capsys.readouterr().out)


def codes(items) -> set[str]:
    return {i["code"] for i in items}


def load_result(envelope) -> AnalysisResult:
    return AnalysisResult.model_validate_json(Path(envelope["summary"]["artifacts"]["analysis"]).read_text())


def test_fasting_polish_czech_full_pipeline(replay_env, capsys):
    code, env = run_cli(capsys, "--topic", "intermittent fasting", "--languages", "pl", "cs", "--no-cache")
    assert code == 0 and env["status"] == "ok"
    s = env["summary"]
    assert s["period"] == {"from": "2024-09", "to": "2026-08", "months": 24}
    assert [t["cluster"] for t in s["topics"]] == [["Přerušovaný půst (Q1666254)"]]
    assert codes(env["warnings"]) >= {"CLUSTER_AUTO_SELECTED", "LANGUAGE_NOT_COVERED"}
    result = load_result(env)
    coverage = {c.project: c.status for c in result.scope.topics[0].coverage}
    assert coverage["pl.wikipedia"] == "missing" and coverage["cs.wikipedia"] == "fetched"
    for name in ("analysis", "request", "report_html", "report_pdf", "chart_relative_attention"):
        assert Path(s["artifacts"][name]).exists(), name
    row = s["per_topic_language"][0]
    m = result.metric("t1", "cs.wikipedia")
    assert row["recent_views"] == round(m.recent_views)
    assert any(f"{m.recent_views:,.0f}" in sentence for sentence in row["rationale"])
    request = json.loads(Path(s["artifacts"]["request"]).read_text())
    assert request["topics"][0]["qids"] == ["Q1666254"]


def test_pdf_is_single_page(replay_env, capsys):
    _, env = run_cli(capsys, "--topic", "astronomy", "--languages", "uk", "de", "--no-cache")
    pdf = Path(env["summary"]["artifacts"]["report_pdf"]).read_bytes()
    assert pdf.count(b"/Type /Page\n") + pdf.count(b"/Type /Page ") + pdf.count(b"/Type /Page/") <= 1
    assert b"/Count 1" in pdf


def test_ambiguous_topic_returns_candidates_without_fetch(replay_env, capsys):
    code, env = run_cli(capsys, "--topic", "mercury", "--languages", "en", "--no-cache")
    assert code == 2 and env["status"] == "needs_confirmation"
    assert codes(env["errors"]) == {"AMBIGUOUS_TOPIC"}
    labels = [c["label"].lower() for c in env["candidates"][0]["candidates"]]
    assert "mercury" in labels and "freddie mercury" in labels
    assert env["run_dir"] is None


def test_broad_topic_is_not_auto_clustered(replay_env, capsys):
    code, env = run_cli(capsys, "--topic", "learning English", "--languages", "pl", "cs", "uk", "--no-cache")
    assert code == 2
    assert all(c["description"] is None or isinstance(c["description"], str)
               for c in env["candidates"][0]["candidates"])


def test_country_only_is_unsupported(replay_env, capsys):
    request = replay_env / "r.json"
    request.write_text(json.dumps({"topics": [{"query": "astronomy"}], "dimensions": ["country"],
                                   "countries": ["PL"]}))
    code, env = run_cli(capsys, "--request", str(request))
    assert code == 1 and codes(env["errors"]) == {"UNSUPPORTED_DIMENSION"}


def test_country_with_languages_is_a_warning(replay_env, capsys):
    code, env = run_cli(capsys, "--topic", "astronomy", "--languages", "uk", "--country", "PL", "--no-cache")
    assert code == 0 and "UNSUPPORTED_DIMENSION" in codes(env["warnings"])
    assert load_result(env).scope.dimensions_unsupported == ["country"]


def test_wrong_language_code_gets_hint(replay_env, capsys):
    code, env = run_cli(capsys, "--topic", "astronomy", "--languages", "cz", "--no-cache")
    assert code == 1
    err = env["errors"][0]
    assert err["code"] == "UNSUPPORTED_LANGUAGE" and "'cs'" in err["hint"]


def test_too_many_topics(replay_env, capsys):
    code, env = run_cli(capsys, "--topic", "a", "--topic", "b", "--topic", "c", "--topic", "d")
    assert code == 1 and codes(env["errors"]) == {"TOO_MANY_TOPICS"}


def test_two_topics_compared_as_pairs(replay_env, capsys):
    code, env = run_cli(capsys, "--topic", "intermittent fasting", "--topic", "ketogenic diet",
                        "--languages", "pl", "cs", "--no-cache")
    assert code == 0
    keys = {r["key"] for r in env["summary"]["per_topic_language"]}
    assert {"t1:cs.wikipedia", "t2:cs.wikipedia"} <= keys
    result = load_result(env)
    assert set(result.comparison.candidates) == keys


def test_default_languages_are_limited_and_reported(replay_env, capsys):
    code, env = run_cli(capsys, "--qids", "Q333", "--no-cache")
    assert code == 0
    assert "LANGUAGE_COVERAGE_LIMITED" in codes(env["warnings"])
    assert len(env["summary"]["languages"]) == 10
    result = load_result(env)
    statuses = {c.status for c in result.scope.topics[0].coverage}
    assert statuses == {"fetched", "not_requested"}


def test_follow_ups_reuse_cache_and_version_requests(replay_env, capsys):
    _, first = run_cli(capsys, "--topic", "astronomy", "--languages", "uk")
    run_id = first["summary"]["run_id"]
    assert first["summary"]["cache"]["http_requests"] > 0

    _, german = run_cli(capsys, "--parent", run_id, "--add-languages", "de")
    assert german["status"] == "ok"
    assert german["summary"]["parent_run_id"] == run_id
    assert german["summary"]["languages"] == ["uk", "de"]
    result = load_result(german)
    assert result.request_version == 2
    per_article = next(s.requests for s in result.scope.sources if "per-article" in s.endpoint)
    de_titles = sum(len(c.titles) for ps in result.series if ps.project == "de.wikipedia" for c in ps.components)
    assert per_article == de_titles  # Ukrainian views came from cache; only German titles fetched

    _, short = run_cli(capsys, "--parent", german["summary"]["run_id"], "--months", "12")
    assert short["summary"]["cache"]["http_requests"] == 0
    assert short["summary"]["period"]["months"] == 12
    assert "INSUFFICIENT_HISTORY" in codes(short["warnings"])
    assert load_result(short).request_version == 3

    _, weighted = run_cli(capsys, "--parent", run_id, "--weights", "growth=2,scale=1")
    assert weighted["summary"]["cache"]["http_requests"] == 0
    assert weighted["summary"]["weighted_order"] is not None


def test_render_only_does_not_recompute(replay_env, capsys, monkeypatch):
    _, env = run_cli(capsys, "--topic", "astronomy", "--languages", "uk", "--no-cache", "--format", "html")
    run_dir = env["run_dir"]
    import interest_signals.analysis.metrics as metrics

    monkeypatch.setattr(metrics, "compute_pair_metrics", lambda *a: pytest.fail("recomputed"))
    code, rendered = run_cli(capsys, "--render", run_dir, "--format", "pdf")
    assert code == 0 and Path(rendered["summary"]["artifacts"]["report_pdf"]).exists()


def test_unknown_run(replay_env, capsys):
    code, env = run_cli(capsys, "--render", "nope")
    assert code == 1 and codes(env["errors"]) == {"RUN_NOT_FOUND"}


def test_cache_commands(replay_env, capsys):
    run_cli(capsys, "--topic", "astronomy", "--languages", "uk")
    code, env = run_cli(capsys, "cache", "status")
    assert code == 0 and env["summary"]["cache"]["monthly_observations"] > 0
    _, cleared = run_cli(capsys, "cache", "clear")
    assert cleared["summary"]["cache"]["removed"] is True


def test_multi_entity_cluster_dedupes_and_reports_components(replay_env, capsys):
    code, env = run_cli(capsys, "--qids", "Q1666254,Q44602,Q1666254", "--languages", "pl", "cs", "--no-cache")
    assert code == 0
    result = load_result(env)
    assert [e.key for e in result.scope.topics[0].cluster] == ["Q1666254", "Q44602"]
    assert "CLUSTER_COVERAGE_INCOMPLETE" in codes(env["warnings"])  # fasting article missing in pl
    cs = next(s for s in result.series if s.project == "cs.wikipedia")
    assert {c.entity_key for c in cs.components} == {"Q1666254", "Q44602"}
    # cluster series is the sum of component raw views, month by month
    for i, total in enumerate(cs.views):
        if total is not None:
            assert total == sum(c.views[i] or 0 for c in cs.components)
    shares = [c.recent_share for c in cs.components]
    assert abs(sum(shares) - 1) < 1e-9
    pl = next(s for s in result.series if s.project == "pl.wikipedia")
    assert [c.entity_key for c in pl.components] == ["Q44602"]


def test_single_entity_without_article_in_languages_is_empty_cluster(replay_env, capsys):
    code, env = run_cli(capsys, "--qids", "Q1666254", "--languages", "pl", "--no-cache")
    assert code == 1 and codes(env["errors"]) == {"EMPTY_CLUSTER"}


def test_changed_cluster_is_recomputed_from_cache(replay_env, capsys):
    _, first = run_cli(capsys, "--qids", "Q1666254", "--languages", "cs")
    request = replay_env / "changed.json"
    base = json.loads(Path(first["summary"]["artifacts"]["request"]).read_text())
    base["topics"][0]["qids"] = ["Q1666254", "Q44602"]
    request.write_text(json.dumps(base))
    _, second = run_cli(capsys, "--request", str(request), "--parent", first["summary"]["run_id"])
    result = load_result(second)
    assert result.request_version == 2 and result.parent_run_id == first["summary"]["run_id"]
    assert len(result.scope.topics[0].cluster) == 2
    assert result.cache.hits > 0


def test_follow_up_after_default_languages_keeps_them(replay_env, capsys):
    _, first = run_cli(capsys, "--qids", "Q333", "--no-cache")
    assert len(first["summary"]["languages"]) == 10
    pinned = json.loads(Path(first["summary"]["artifacts"]["request"]).read_text())
    assert pinned["languages"] == first["summary"]["languages"]
    assert pinned["end_month"] == "2026-08"
    run_cli(capsys, "--qids", "Q333")  # warm the cache for the follow-up
    _, second = run_cli(capsys, "--parent", first["summary"]["run_id"], "--add-languages", "uk")
    assert second["summary"]["languages"] == [*first["summary"]["languages"], "uk"]
    result = load_result(second)
    per_article = next(s.requests for s in result.scope.sources if "per-article" in s.endpoint)
    uk_titles = sum(len(c.titles) for ps in result.series if ps.project == "uk.wikipedia" for c in ps.components)
    assert per_article == uk_titles  # the ten earlier languages came from cache


def _failing_transport(predicate):
    import httpx

    from interest_signals.providers.wikipedia.replay import ReplayTransport
    from tests.conftest import FIXTURES

    replay = ReplayTransport(FIXTURES)

    def handler(request: httpx.Request) -> httpx.Response:
        if predicate(str(request.url)):
            return httpx.Response(503, text="Service Unavailable")
        return replay.handle_request(request)

    return httpx.MockTransport(handler)


def test_outage_during_search_is_api_unavailable(replay_env, capsys, monkeypatch):
    from interest_signals import config
    from interest_signals.providers.wikipedia import client

    monkeypatch.setattr(config, "MAX_RETRIES", 1)
    monkeypatch.setattr(client.time, "sleep", lambda s: None)
    monkeypatch.setattr(client, "transport_from_env", lambda: _failing_transport(lambda u: "gsrsearch" in u))
    code, env = run_cli(capsys, "--topic", "astronomy", "--languages", "uk", "--no-cache")
    assert code == 1
    err = env["errors"][0]
    assert err["code"] == "API_UNAVAILABLE" and "retry" in err["hint"]


def test_outage_on_one_language_marks_months_unavailable(replay_env, capsys, monkeypatch):
    from interest_signals import config
    from interest_signals.providers.wikipedia import client

    monkeypatch.setattr(config, "MAX_RETRIES", 1)
    monkeypatch.setattr(client.time, "sleep", lambda s: None)
    monkeypatch.setattr(client, "transport_from_env",
                        lambda: _failing_transport(lambda u: "per-article/de.wikipedia" in u))
    code, env = run_cli(capsys, "--topic", "astronomy", "--languages", "uk", "de", "--no-cache")
    assert code == 0
    assert "PARTIAL_DATA" in codes(env["warnings"])
    result = load_result(env)
    de = next(s for s in result.series if s.project == "de.wikipedia")
    assert set(de.status) == {"unavailable"} and all(v is None for v in de.views)
    assert result.metric("t1", "de.wikipedia").recent_views is None
    uk = next(s for s in result.series if s.project == "uk.wikipedia")
    assert "ok" in uk.status
