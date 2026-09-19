"""Load data/raw Parquet into Snowflake RAW via an internal stage, in one transaction.

One snapshot in, one snapshot applied. PUT the files, then DELETE + COPY INTO every
table inside a single transaction so a mid-load failure rolls back to the previous
snapshot rather than leaving RAW half-new. FORCE = TRUE because Snowflake remembers
loaded files and would otherwise skip a re-PUT of the same name after DELETE emptied
the table.

Refuses to load an incomplete or inconsistent snapshot: every table in TABLE_ORDER
must be present, none may be empty, write times must sit inside a 10-minute window
(the generator writes them in one call), and the referential checks the generator
already enforces are re-checked here so a partial copy of data/raw cannot land.

Usage:
    python infra/snowflake/load_raw.py --raw-dir data/raw --env-file .env.snowflake.local

Optional:
    --raw-schema CI_PR_4_RAW     per-PR RAW schema (default RAW)
    --stage-wheel                also PUT the slim metrics wheel to RAW.LP_LENS_PACKAGES
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

import sfconn  # noqa: E402
from lp_lens.generate.writer import TABLE_ORDER, TABLE_SCHEMAS  # noqa: E402

MAX_SNAPSHOT_SPREAD = dt.timedelta(minutes=10)
DEFAULT_RAW_SCHEMA = "RAW"
DEFAULT_STAGE = "LP_LENS_RAW"
DEFAULT_FILE_FORMAT = "LP_LENS_PARQUET"
DEFAULT_PACKAGES_STAGE = "LP_LENS_PACKAGES"

# Arrow type -> Snowflake type. The generator pins these; COPY MATCH_BY_COLUMN_NAME
# is case-insensitive so the Parquet field names do not have to match identifier case.
_SNOWFLAKE_TYPE = {
    pa.string(): "VARCHAR",
    pa.int16(): "INTEGER",
    pa.float64(): "FLOAT",
    pa.date32(): "DATE",
}


class SnapshotError(Exception):
    """The local snapshot is incomplete or inconsistent. load() turns this into SystemExit."""


def snowflake_type(field: pa.Field) -> str:
    for arrow_type, sql_type in _SNOWFLAKE_TYPE.items():
        if field.type == arrow_type:
            return sql_type
    raise SnapshotError(f"ABORT: no Snowflake type mapped for {field.name} {field.type}")


def create_table_sql(schema_name: str, table: str) -> str:
    columns = ", ".join(f"{field.name} {snowflake_type(field)}" for field in TABLE_SCHEMAS[table])
    return f"CREATE TABLE IF NOT EXISTS {schema_name}.{table} ({columns})"


def parquet_paths(raw_dir: Path) -> dict[str, Path]:
    return {name: raw_dir / f"{name}.parquet" for name in TABLE_ORDER}


def check_snapshot(raw_dir: Path) -> dict[str, int]:
    """Inspect the local Parquet directory. Returns row counts if the snapshot is usable.

    Does not touch Snowflake. A failure here leaves the previous RAW snapshot in place
    because load() never opens a transaction until this returns.
    """
    raw_dir = Path(raw_dir)
    if not raw_dir.is_dir():
        raise SnapshotError(f"ABORT: raw directory {raw_dir} does not exist")

    paths = parquet_paths(raw_dir)
    missing = [name for name, path in paths.items() if not path.is_file()]
    if missing:
        raise SnapshotError(f"ABORT: raw/ is missing {missing}; not a complete snapshot")

    stamps = [dt.datetime.fromtimestamp(path.stat().st_mtime, tz=dt.UTC) for path in paths.values()]
    spread = max(stamps) - min(stamps)
    if spread > MAX_SNAPSHOT_SPREAD:
        raise SnapshotError(f"ABORT: raw/ file write times differ by {spread}; not one generator run")

    frames = {name: pq.read_table(path).to_pandas() for name, path in paths.items()}
    counts = {name: len(frame) for name, frame in frames.items()}
    empty = [name for name, n in counts.items() if n == 0]
    if empty:
        raise SnapshotError(f"ABORT: raw/ tables are empty: {empty}")

    _assert_referential(frames)
    return counts


def _assert_referential(frames: dict[str, pd.DataFrame]) -> None:
    """The same joins the warehouse will make. Fail here rather than load a broken RAW."""
    managers = set(frames["managers"]["manager_id"])
    funds = set(frames["funds"]["fund_id"])
    investors = set(frames["investors"]["investor_id"])
    orphan_funds = set(frames["funds"]["manager_id"]) - managers
    if orphan_funds:
        raise SnapshotError(f"ABORT: funds reference missing managers: {sorted(orphan_funds)[:5]}")

    commitments = frames["commitments"]
    if set(commitments["fund_id"]) - funds:
        raise SnapshotError("ABORT: commitments reference a fund that is not in funds")
    if set(commitments["investor_id"]) - investors:
        raise SnapshotError("ABORT: commitments reference an investor that is not in investors")
    pairs = set(zip(commitments["fund_id"], commitments["investor_id"], strict=True))

    for table in ("cash_flows", "nav"):
        unknown = set(zip(frames[table]["fund_id"], frames[table]["investor_id"], strict=True)) - pairs
        if unknown:
            raise SnapshotError(f"ABORT: {table} has rows that do not resolve to a commitment")


def load(
    raw_dir: Path,
    *,
    raw_schema: str = DEFAULT_RAW_SCHEMA,
    stage_wheel: bool = False,
) -> dict[str, int]:
    """PUT the snapshot and swap RAW tables inside one transaction. Returns loaded counts."""
    expected = check_snapshot(raw_dir)
    paths = parquet_paths(raw_dir)

    try:
        con = sfconn.connect("lp-lens-load-raw")
    except Exception as exc:
        raise SystemExit(f"[load] could not connect: {sfconn.mask(exc)}") from None

    try:
        cur = con.cursor()
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {raw_schema}")
        cur.execute(
            f"CREATE FILE FORMAT IF NOT EXISTS {raw_schema}.{DEFAULT_FILE_FORMAT} "
            "TYPE = PARQUET USE_LOGICAL_TYPE = TRUE"
        )
        cur.execute(
            f"CREATE STAGE IF NOT EXISTS {raw_schema}.{DEFAULT_STAGE} "
            f"FILE_FORMAT = (FORMAT_NAME = {raw_schema}.{DEFAULT_FILE_FORMAT})"
        )
        for table, path in paths.items():
            cur.execute(create_table_sql(raw_schema, table))
            put = (
                f"PUT file://{path.resolve()} @{raw_schema}.{DEFAULT_STAGE}/{table}.parquet "
                "AUTO_COMPRESS = FALSE OVERWRITE = TRUE"
            )
            try:
                cur.execute(put)
            except Exception as exc:
                raise SystemExit(f"[load] PUT {table} failed: {sfconn.mask(exc)}") from None

        if stage_wheel:
            _stage_metrics_wheel(cur, database_schema=raw_schema)

        cur.execute("BEGIN")
        try:
            for table in TABLE_ORDER:
                cur.execute(f"DELETE FROM {raw_schema}.{table}")
                cur.execute(
                    f"COPY INTO {raw_schema}.{table} "
                    f"FROM @{raw_schema}.{DEFAULT_STAGE} "
                    f"FILES = ('{table}.parquet') "
                    f"FILE_FORMAT = (FORMAT_NAME = {raw_schema}.{DEFAULT_FILE_FORMAT}) "
                    "MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE FORCE = TRUE "
                    "ON_ERROR = ABORT_STATEMENT"
                )
                cur.execute(f"SELECT COUNT(*) FROM {raw_schema}.{table}")
                loaded = int(cur.fetchone()[0])
                if loaded != expected[table]:
                    raise SnapshotError(
                        f"ABORT: {raw_schema}.{table} loaded {loaded} rows, local parquet has {expected[table]}"
                    )
            cur.execute("COMMIT")
        except Exception:
            cur.execute("ROLLBACK")
            raise
    except SnapshotError as exc:
        raise SystemExit(str(exc)) from None
    except Exception as exc:
        raise SystemExit(f"[load] failed: {sfconn.mask(exc)}") from None
    finally:
        con.close()

    for table, n in expected.items():
        print(f"[load] {raw_schema}.{table:<16} {n:>8} rows")
    return expected


def _stage_metrics_wheel(cur, *, database_schema: str) -> Path:
    from build_metrics_wheel import build_metrics_wheel

    wheel = build_metrics_wheel()
    cur.execute(f"CREATE STAGE IF NOT EXISTS {database_schema}.{DEFAULT_PACKAGES_STAGE}")
    cur.execute(
        f"PUT file://{wheel.resolve()} @{database_schema}.{DEFAULT_PACKAGES_STAGE} "
        "AUTO_COMPRESS = FALSE OVERWRITE = TRUE"
    )
    print(f"[load] staged metrics wheel {wheel.name} to @{database_schema}.{DEFAULT_PACKAGES_STAGE}")
    return wheel


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--raw-schema", default=DEFAULT_RAW_SCHEMA, help="Snowflake schema to load into")
    parser.add_argument("--env-file", type=Path, help="KEY=VALUE file, e.g. .env.snowflake.local")
    parser.add_argument(
        "--stage-wheel",
        action="store_true",
        help="also PUT the slim lp_lens metrics wheel so Snowpark Python models can import it",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="validate the local snapshot and exit, without connecting to Snowflake",
    )
    args = parser.parse_args(argv)
    if args.env_file:
        sfconn.read_env_file(args.env_file)

    if args.check_only:
        try:
            counts = check_snapshot(args.raw_dir)
        except SnapshotError as exc:
            raise SystemExit(str(exc)) from None
        for table, n in counts.items():
            print(f"[check] {table:<16} {n:>8} rows")
        return 0

    load(args.raw_dir, raw_schema=args.raw_schema, stage_wheel=args.stage_wheel)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
