#!/usr/bin/env python3
"""Entry point for the interest-signals skill.

This file is a stdlib-only bootstrap. It must stay importable by old Python versions so that
an unsupported interpreter gets a structured JSON error instead of a SyntaxError.

It prepares a local virtual environment inside the skill directory with pip only (never outside
it; the stdlib `venv` module plus pip, or the official pip zipapp when pip is missing), then
runs ``interest_signals.cli`` inside that environment as a child process. The child writes the
JSON envelope to stdout; its exit code is returned unchanged.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENV_DIR = os.path.join(SKILL_DIR, ".venv")
TOOLS_DIR = os.path.join(SKILL_DIR, ".venv-tools")
LOCK_FILE = os.path.join(SKILL_DIR, "requirements.lock")
HASH_MARKER = os.path.join(VENV_DIR, ".lock-hash")
INSTALL_LOG = os.path.join(TOOLS_DIR, "install.log")
MIN_PYTHON = (3, 12)

PIP_ZIPAPP_URL = "https://bootstrap.pypa.io/pip/zipapp/pip-26.2.1.pyz"
PIP_ZIPAPP_SHA256 = "91d5fd9f6f25549fd839c60536c6f1b945316ce3588d34a605635b6071c91526"


class BootstrapError(Exception):
    def __init__(self, code, message, hint, context=None):
        Exception.__init__(self, message)
        self.code = code
        self.message = message
        self.hint = hint
        self.context = context or {}


def emit_error(err):
    envelope = {
        "status": "error",
        "run_dir": None,
        "summary": None,
        "candidates": [],
        "errors": [
            {
                "code": err.code,
                "severity": "error",
                "message": err.message,
                "hint": err.hint,
                "context": err.context,
            }
        ],
        "warnings": [],
    }
    sys.stdout.write(json.dumps(envelope, ensure_ascii=False, indent=2) + "\n")


def log(message):
    sys.stderr.write("[interest-signals] " + message + "\n")


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def venv_python():
    if os.name == "nt":
        return os.path.join(VENV_DIR, "Scripts", "python.exe")
    return os.path.join(VENV_DIR, "bin", "python")


def check_python():
    if tuple(sys.version_info[:2]) < MIN_PYTHON:
        raise BootstrapError(
            "RUNTIME_UNSUPPORTED_PYTHON",
            "Python %d.%d found; interest-signals needs Python %d.%d or newer."
            % (sys.version_info[0], sys.version_info[1], MIN_PYTHON[0], MIN_PYTHON[1]),
            "Run the script with Python 3.12+ (for example `python3.12 scripts/analyze.py`). "
            "The skill never installs Python itself.",
        )


def env_is_ready(lock_hash):
    if not os.path.exists(venv_python()) or not os.path.exists(HASH_MARKER):
        return False
    with open(HASH_MARKER) as fh:
        return fh.read().strip() == lock_hash


def run_logged(cmd, env=None):
    os.makedirs(TOOLS_DIR, exist_ok=True)
    with open(INSTALL_LOG, "a") as out:
        out.write("$ " + " ".join(cmd) + "\n")
        out.flush()
        return subprocess.call(cmd, stdout=out, stderr=subprocess.STDOUT, cwd=SKILL_DIR, env=env)


def log_tail(lines=20):
    try:
        with open(INSTALL_LOG) as fh:
            return "".join(fh.readlines()[-lines:])
    except OSError:
        return ""


def install_failed(step):
    raise BootstrapError(
        "DEPENDENCY_INSTALL_FAILED",
        "Could not install dependencies (%s)." % step,
        "Check network access to PyPI, then rerun. Full log: %s" % INSTALL_LOG,
        {"log_tail": log_tail()},
    )


def has_ensurepip():
    try:
        import ensurepip  # noqa: F401
    except ImportError:
        return False
    return True


def fetch_pip_zipapp():
    os.makedirs(TOOLS_DIR, exist_ok=True)
    target = os.path.join(TOOLS_DIR, "pip.pyz")
    if os.path.exists(target) and file_sha256(target) == PIP_ZIPAPP_SHA256:
        return target
    tmp = target + ".part"
    try:
        log("pip is not available; downloading the official pip zipapp into .venv-tools/")
        urllib.request.urlretrieve(PIP_ZIPAPP_URL, tmp)
    except Exception as exc:  # network errors, proxies, SSL
        raise BootstrapError(
            "PYTHON_VENV_UNAVAILABLE",
            "This Python has no pip/ensurepip and the pip zipapp could not be downloaded (%s)." % exc,
            "Install your OS package `python3-venv` (or `python3-pip`), then rerun. "
            "The skill does not install system packages itself.",
        ) from exc
    if file_sha256(tmp) != PIP_ZIPAPP_SHA256:
        os.remove(tmp)
        raise BootstrapError(
            "PYTHON_VENV_UNAVAILABLE",
            "Downloaded pip zipapp failed the sha256 check.",
            "Install your OS package `python3-venv`, then rerun.",
        )
    os.replace(tmp, target)
    return target


def install_with_pip():
    if os.path.exists(VENV_DIR):
        shutil.rmtree(VENV_DIR)
    requirement_args = ["install", "--require-hashes", "--no-deps", "-r", LOCK_FILE]
    if has_ensurepip():
        if run_logged([sys.executable, "-m", "venv", VENV_DIR]) != 0:
            install_failed("python -m venv")
        if run_logged([venv_python(), "-m", "pip"] + requirement_args) != 0:
            install_failed("pip install")
        return
    zipapp = fetch_pip_zipapp()
    if run_logged([sys.executable, "-m", "venv", "--without-pip", VENV_DIR]) != 0:
        install_failed("python -m venv --without-pip")
    if run_logged([sys.executable, zipapp, "--python", venv_python()] + requirement_args) != 0:
        install_failed("pip zipapp install")


def ensure_env():
    """Create or refresh the skill-local environment. Returns the venv interpreter path."""
    check_python()
    lock_hash = file_sha256(LOCK_FILE)
    if env_is_ready(lock_hash):
        return venv_python()
    log("preparing local environment in %s (first run takes about a minute)" % VENV_DIR)
    install_with_pip()
    with open(HASH_MARKER, "w") as fh:
        fh.write(lock_hash)
    return venv_python()


def child_env():
    env = dict(os.environ)
    src = os.path.join(SKILL_DIR, "src")
    env["PYTHONPATH"] = src + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


def main(argv):
    try:
        python = ensure_env()
    except BootstrapError as err:
        emit_error(err)
        return 1
    return subprocess.call([python, "-m", "interest_signals.cli"] + list(argv), env=child_env())


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
