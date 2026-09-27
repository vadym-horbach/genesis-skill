"""Reports: written only through --render, in the requested language, with the agent's analysis."""

from __future__ import annotations

import json
from pathlib import Path

from interest_signals import cli


def run_cli(capsys, *args: str) -> tuple[int, dict]:
    code = cli.main(list(args))
    return code, json.loads(capsys.readouterr().out)


def analysis_run(capsys) -> dict:
    code, env = run_cli(capsys, "--topic", "astronomy", "--languages", "uk", "de", "--no-cache")
    assert code == 0
    return env


def ukrainian_content(template: dict, row: dict) -> dict:
    views = f"{row['recent_views']:,.0f}".replace(",", " ")
    content = dict(template)
    content["language"] = "uk"
    content["text"] = {k: f"[uk] {v}" for k, v in template["text"].items()}
    content["warnings"] = [f"[uk] {w}" for w in template["warnings"]]
    content["limitations"] = [f"[uk] {x}" for x in template["limitations"]]
    content["details"] = {k: f"[uk] {v}" for k, v in template["details"].items()}
    content["analysis"] = {
        "headline": "Астрономія: стабільна увага без зростання",
        "findings": [f"У {row['key'].split(':')[1]} близько {views} переглядів на місяць."],
        "recommendation": "Спершу перевірити попит іншими даними.",
        "next_steps": ["Порівняти з іншою темою."],
    }
    return content


def test_template_then_localized_render(replay_env, capsys):
    env = analysis_run(capsys)
    run_id = env["summary"]["run_id"]
    _, tpl = run_cli(capsys, "report-template", run_id)
    template = tpl["summary"]["report_template"]
    assert template["language"] == "en" and "title" in template["text"]
    content = ukrainian_content(template, env["summary"]["per_topic_language"][0])
    path = replay_env / "content.json"
    path.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")

    code, rendered = run_cli(capsys, "--render", run_id, "--content", str(path))
    assert code == 0, rendered
    assert "REPORT_UNTRANSLATED" not in {w["code"] for w in rendered["warnings"]}
    artifacts = rendered["summary"]["artifacts"]
    html = Path(artifacts["report_html"]).read_text(encoding="utf-8")
    assert Path(artifacts["report_html"]).parent == replay_env
    assert '<html lang="uk">' in html and "Астрономія: стабільна увага" in html
    assert "<h1>[uk] Interest signals" in html and "<h2>Comparison</h2>" not in html
    pdf = Path(artifacts["report_pdf"]).read_bytes()
    assert b"/Count 1" in pdf

    # a later render without content reuses the saved content
    _, again = run_cli(capsys, "--render", run_id, "--format", "html", "--out", str(replay_env / "out"))
    assert "Астрономія" in Path(again["summary"]["artifacts"]["report_html"]).read_text(encoding="utf-8")


def test_invented_number_is_rejected(replay_env, capsys):
    env = analysis_run(capsys)
    content = {"language": "en", "analysis": {"headline": "Growing 37% a year", "findings": ["x"],
                                                 "recommendation": "y"}}
    path = replay_env / "c.json"
    path.write_text(json.dumps(content))
    code, out = run_cli(capsys, "--render", env["summary"]["run_id"], "--content", str(path))
    assert code == 1 and out["errors"][0]["code"] == "REPORT_CONTENT_INVALID"
    assert out["errors"][0]["context"]["numbers"] == ["37"]
    assert list(replay_env.glob("*.html")) == []


def test_untranslated_parts_are_warned(replay_env, capsys, monkeypatch):
    env = analysis_run(capsys)
    content = {"language": "uk", "analysis": {"headline": "Висновок", "findings": ["Факт."],
                                                 "recommendation": "Порада."}}
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(json.dumps(content)))
    code, out = run_cli(capsys, "--render", env["summary"]["run_id"], "--content", "-", "--format", "html")
    assert code == 0 and "REPORT_UNTRANSLATED" in {w["code"] for w in out["warnings"]}


def test_inline_content_and_repeated_format(replay_env, capsys):
    env = analysis_run(capsys)
    content = {"language": "uk", "analysis": {"headline": "Інтерес м’який, без зростання", "findings": ["Факт."],
                                                 "recommendation": "Порада."}}
    code, out = run_cli(capsys, "--render", env["summary"]["run_id"], "--content-json",
                        json.dumps(content, ensure_ascii=False), "--format", "html", "--format", "pdf")
    assert code == 0 and set(out["summary"]["artifacts"]) == {"report_html", "report_pdf"}
    code, bad = run_cli(capsys, "--render", env["summary"]["run_id"], "--content-json", "{broken")
    assert code == 1 and "apostrophes" in bad["errors"][0]["hint"]


def test_english_render_needs_only_analysis(replay_env, capsys):
    env = analysis_run(capsys)
    row = env["summary"]["per_topic_language"][0]
    content = {"analysis": {"headline": "Astronomy attention is flat",
                            "findings": [f"{row['key']}: about {row['recent_views']:,.0f} views per month."],
                            "recommendation": "Validate with market data first."}}
    path = replay_env / "c.json"
    path.write_text(json.dumps(content))
    code, out = run_cli(capsys, "--render", env["summary"]["run_id"], "--content", str(path))
    assert code == 0 and out["warnings"] is not None
    html = Path(out["summary"]["artifacts"]["report_html"]).read_text()
    assert "Astronomy attention is flat" in html and "Details by topic and edition" in html
