"""Build a slim wheel that contains only lp_lens.metrics — the file Snowpark has to import.

The installable lp-lens package depends on duckdb, pydantic and pyyaml. Those are not on
Snowflake's Anaconda channel, and a full-package wheel would try to pull them in. This
builder copies just:

    lp_lens/__init__.py
    lp_lens/metrics/__init__.py
    lp_lens/metrics/returns.py

into a PEP 427 zip. The import path stays `lp_lens.metrics.returns` — the same module the
DuckDB Python models and the reconciliation tests call. There is no second solver.

A zipfile rather than `pip wheel`: the isolated build frontend needs setuptools in a way
CI cannot assume, and the payload is three source files. RECORD hashes are written so the
archive is a well-formed wheel.

Usage:
    python infra/snowflake/build_metrics_wheel.py
    python infra/snowflake/build_metrics_wheel.py --out-dir /tmp/wheels
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "lp_lens"
VERSION = "0.1.0"
WHEEL_NAME = f"lp_lens-{VERSION}-py3-none-any.whl"
DIST_INFO = f"lp_lens-{VERSION}.dist-info"

_METADATA = f"""Metadata-Version: 2.1
Name: lp-lens
Version: {VERSION}
Summary: Slim Snowpark wheel: lp_lens.metrics.returns only
Requires-Python: >=3.10
"""

_WHEEL = """Wheel-Version: 1.0
Generator: lp_lens.build_metrics_wheel
Root-Is-Purelib: true
Tag: py3-none-any
"""


def _record_line(name: str, data: bytes) -> str:
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode("ascii").rstrip("=")
    return f"{name},sha256={digest},{len(data)}"


def build_metrics_wheel(out_dir: Path | None = None) -> Path:
    """Return the path of the built wheel."""
    dest = Path(out_dir) if out_dir is not None else ROOT / "dist"
    dest.mkdir(parents=True, exist_ok=True)

    payload = {
        "lp_lens/__init__.py": SRC / "__init__.py",
        "lp_lens/metrics/__init__.py": SRC / "metrics" / "__init__.py",
        "lp_lens/metrics/returns.py": SRC / "metrics" / "returns.py",
    }
    missing = [str(path) for path in payload.values() if not path.is_file()]
    if missing:
        raise SystemExit(f"ABORT: metrics sources missing: {missing}")

    contents: list[tuple[str, bytes]] = []
    for arcname, path in payload.items():
        contents.append((arcname, path.read_bytes()))
    contents.append((f"{DIST_INFO}/METADATA", _METADATA.encode("utf-8")))
    contents.append((f"{DIST_INFO}/WHEEL", _WHEEL.encode("utf-8")))

    record = "".join(_record_line(name, data) + "\n" for name, data in contents)
    record += f"{DIST_INFO}/RECORD,,\n"
    contents.append((f"{DIST_INFO}/RECORD", record.encode("utf-8")))

    wheel = dest / WHEEL_NAME
    with zipfile.ZipFile(wheel, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in contents:
            archive.writestr(name, data)
    return wheel


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    print(build_metrics_wheel(args.out_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
