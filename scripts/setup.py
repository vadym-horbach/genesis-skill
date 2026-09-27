#!/usr/bin/env python3
"""Prepare the skill-local environment ahead of the first analysis (optional pre-warm)."""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import analyze  # noqa: E402  (sibling bootstrap module, stdlib only)


def main():
    try:
        python = analyze.ensure_env()
    except analyze.BootstrapError as err:
        analyze.emit_error(err)
        return 1
    envelope = {
        "status": "ok",
        "run_dir": None,
        "summary": {"environment": python},
        "candidates": [],
        "errors": [],
        "warnings": [],
    }
    sys.stdout.write(json.dumps(envelope, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
