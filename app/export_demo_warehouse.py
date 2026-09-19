"""Copy mart tables from a local dbt DuckDB build into the committed demo file.

Run from the repository root after `dbt build --target local`:

    python app/export_demo_warehouse.py
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
# Do not read LP_LENS_DB_PATH: sqlfluff and CI point that at an empty lint stub.
SOURCE = Path(os.environ.get("LP_LENS_SOURCE_DB", ROOT / "data" / "warehouse" / "lp_lens.duckdb"))
DEST = ROOT / "app" / "data" / "demo.duckdb"
MANIFEST = ROOT / "warehouse" / "target" / "manifest.json"
BUILD_INFO = ROOT / "app" / "data" / "build_info.json"

TABLES = (
    "dim_fund",
    "dim_manager",
    "dim_investor",
    "dim_strategy",
    "fct_fund_performance_quarterly",
    "fct_portfolio_performance_quarterly",
)


def main() -> int:
    if not SOURCE.is_file():
        raise SystemExit(f"source warehouse missing: {SOURCE}")
    DEST.parent.mkdir(parents=True, exist_ok=True)
    tmp = DEST.with_suffix(".tmp.duckdb")
    if tmp.exists():
        tmp.unlink()
    src = duckdb.connect(str(SOURCE), read_only=True)
    dst = duckdb.connect(str(tmp))
    dst.execute("CREATE SCHEMA marts")
    counts = {}
    for table in TABLES:
        frame = src.execute(f"select * from marts.{table}").df()
        dst.register("_export", frame)
        dst.execute(f"CREATE TABLE marts.{table} AS SELECT * FROM _export")
        dst.unregister("_export")
        counts[table] = int(dst.execute(f"select count(*) from marts.{table}").fetchone()[0])
    as_of = dst.execute(
        "select max(as_of_quarter) from marts.fct_portfolio_performance_quarterly where is_latest_quarter"
    ).fetchone()[0]
    dst.execute("CHECKPOINT")
    dst.close()
    src.close()
    shutil.move(tmp, DEST)

    generated_at = None
    if MANIFEST.is_file():
        generated_at = json.loads(MANIFEST.read_text(encoding="utf-8"))["metadata"]["generated_at"]
    BUILD_INFO.write_text(
        json.dumps(
            {
                "dbt_generated_at": generated_at,
                "as_of_quarter": str(as_of),
                "tables": list(TABLES),
                "row_counts": counts,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {DEST} ({DEST.stat().st_size} bytes)")
    for table, n in counts.items():
        print(f"  {table:<40} {n:>6}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
