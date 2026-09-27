"""scripts/analyze.py bootstrap: stdlib only, never downloads Python, forwards exit codes."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "analyze.py"


@pytest.fixture
def boot(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("boot_analyze", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "VENV_DIR", str(tmp_path / ".venv"))
    monkeypatch.setattr(module, "TOOLS_DIR", str(tmp_path / ".venv-tools"))
    monkeypatch.setattr(module, "HASH_MARKER", str(tmp_path / ".venv" / ".lock-hash"))
    monkeypatch.setattr(module, "INSTALL_LOG", str(tmp_path / ".venv-tools" / "install.log"))
    return module


def test_bootstrap_uses_pip_only():
    source = SCRIPT.read_text()
    assert "uv" not in source.replace("urlretrieve", "")


def test_unsupported_python_is_structured(boot, monkeypatch, capsys):
    monkeypatch.setattr(boot, "MIN_PYTHON", (99, 0))
    assert boot.main([]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "error"
    assert out["errors"][0]["code"] == "RUNTIME_UNSUPPORTED_PYTHON"


def test_ready_env_skips_install_and_forwards_exit_code(boot, monkeypatch, tmp_path):
    python = Path(boot.venv_python())
    python.parent.mkdir(parents=True)
    python.write_text("")
    Path(boot.HASH_MARKER).write_text(boot.file_sha256(boot.LOCK_FILE))
    monkeypatch.setattr(boot, "install_with_pip", lambda: pytest.fail("must not reinstall"))
    seen = {}

    def fake_call(cmd, env=None, **kw):
        seen["cmd"], seen["env"] = cmd, env
        return 2

    monkeypatch.setattr(boot.subprocess, "call", fake_call)
    assert boot.main(["--version"]) == 2
    assert seen["cmd"][1:] == ["-m", "interest_signals.cli", "--version"]
    assert seen["env"]["PYTHONPATH"].split(boot.os.pathsep)[0].endswith("src")


def test_changed_lock_triggers_reinstall(boot, monkeypatch):
    python = Path(boot.venv_python())
    python.parent.mkdir(parents=True)
    python.write_text("")
    Path(boot.HASH_MARKER).write_text("stale")
    calls = []
    monkeypatch.setattr(boot, "install_with_pip", lambda: calls.append("pip"))
    boot.ensure_env()
    assert calls == ["pip"]
    assert Path(boot.HASH_MARKER).read_text() == boot.file_sha256(boot.LOCK_FILE)


def test_pip_zipapp_download_failure_is_structured(boot, monkeypatch):
    def fail(*a, **k):
        raise OSError("offline")

    monkeypatch.setattr(boot.urllib.request, "urlretrieve", fail)
    with pytest.raises(boot.BootstrapError) as exc:
        boot.fetch_pip_zipapp()
    assert exc.value.code == "PYTHON_VENV_UNAVAILABLE"


def test_bootstrap_parses_on_old_python():
    import ast

    for name in ("analyze.py", "setup.py"):
        ast.parse((SCRIPT.parent / name).read_text(), feature_version=(3, 8))


def test_output_schema_doc_is_current():
    import subprocess

    root = SCRIPT.parents[1]
    result = subprocess.run(
        [sys.executable, str(root / "dev" / "gen_schema.py"), "--check"],
        env={"PYTHONPATH": str(root / "src")}, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
