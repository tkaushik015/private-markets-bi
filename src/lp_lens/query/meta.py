"""Build provenance for the footer: dbt manifest time and git SHA. Not metrics."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
BUILD_INFO = REPO_ROOT / "app" / "data" / "build_info.json"
MANIFEST = REPO_ROOT / "warehouse" / "target" / "manifest.json"


def dbt_generated_at() -> str | None:
    """Prefer a freshly compiled manifest; fall back to the stamp shipped with the demo file."""
    if MANIFEST.is_file():
        try:
            stamp = json.loads(MANIFEST.read_text(encoding="utf-8"))["metadata"]["generated_at"]
            if stamp:
                return str(stamp)
        except (KeyError, json.JSONDecodeError, TypeError):
            pass
    if BUILD_INFO.is_file():
        try:
            stamp = json.loads(BUILD_INFO.read_text(encoding="utf-8")).get("dbt_generated_at")
            if stamp:
                return str(stamp)
        except json.JSONDecodeError:
            pass
    return None


def git_sha() -> str | None:
    env = os.environ.get("GITHUB_SHA") or os.environ.get("LP_LENS_GIT_SHA")
    if env:
        return env[:12]
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        sha = result.stdout.strip()
        return sha or None
    except (OSError, subprocess.CalledProcessError):
        return None
