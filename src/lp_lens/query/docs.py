"""Render the dbt YAML/docs blocks. The app displays them; it does not rewrite the formulae."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCS_PATH = REPO_ROOT / "warehouse" / "models" / "marts" / "_metric_definitions.md"

_DOCS_BLOCK = re.compile(
    r"\{%\s*docs\s+(?P<name>\w+)\s*%\}\s*(?P<body>.*?)\s*\{%\s*enddocs\s*%\}",
    re.DOTALL,
)


def load_metric_docs(path: Path | None = None) -> list[dict[str, str]]:
    """Return the `{% docs %}` blocks from the mart metric definitions, in file order."""
    text = (path or DOCS_PATH).read_text(encoding="utf-8")
    blocks = []
    for match in _DOCS_BLOCK.finditer(text):
        name = match.group("name")
        body = match.group("body").strip()
        title = name.replace("metric_", "").replace("_", " ").upper()
        if name == "as_of_convention":
            title = "As-of convention"
        elif name.startswith("metric_"):
            title = name.removeprefix("metric_").replace("_", " ").upper()
        blocks.append({"name": name, "title": title, "body": body})
    if not blocks:
        raise ValueError(f"no {{% docs %}} blocks found in {path or DOCS_PATH}")
    return blocks
