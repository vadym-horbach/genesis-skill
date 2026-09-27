#!/usr/bin/env sh
# Regenerate the hash-pinned requirements.lock used by scripts/analyze.py (pip only).
# Needs pip-tools: python -m pip install -e ".[dev]"  (or pip install pip-tools)
set -eu
cd "$(dirname "$0")/.."
python -m piptools compile --quiet --generate-hashes --strip-extras --allow-unsafe \
    --no-header --output-file requirements.lock pyproject.toml
