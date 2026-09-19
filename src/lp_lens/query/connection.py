"""DuckDB (default) or Snowflake connections. Credentials stay in the environment."""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
DEMO_DB = REPO_ROOT / "app" / "data" / "demo.duckdb"

SOURCE_ENV = "LP_LENS_APP_SOURCE"
SOURCE_DUCKDB = "duckdb"
SOURCE_SNOWFLAKE = "snowflake"


def active_source() -> str:
    """Default is the committed synthetic DuckDB file. Snowflake is opt-in."""
    value = os.environ.get(SOURCE_ENV, SOURCE_DUCKDB).strip().lower()
    if value not in {SOURCE_DUCKDB, SOURCE_SNOWFLAKE}:
        raise ValueError(f"{SOURCE_ENV} must be {SOURCE_DUCKDB!r} or {SOURCE_SNOWFLAKE!r}, got {value!r}")
    return value


def demo_db_path() -> Path:
    override = os.environ.get("LP_LENS_DEMO_DB")
    return Path(override) if override else DEMO_DB


def read_sql(sql: str, params: tuple | list | None = None) -> pd.DataFrame:
    """Run a SELECT against the active warehouse. No writes."""
    source = active_source()
    if source == SOURCE_SNOWFLAKE:
        return _read_snowflake(sql, params)
    return _read_duckdb(sql, params)


def _read_duckdb(sql: str, params: tuple | list | None) -> pd.DataFrame:
    import duckdb

    path = demo_db_path()
    if not path.is_file():
        raise FileNotFoundError(
            f"Demo warehouse not found at {path}. Build it with "
            "`python app/export_demo_warehouse.py` after a local dbt build."
        )
    con = duckdb.connect(str(path), read_only=True)
    try:
        return con.execute(sql, params or []).df()
    finally:
        con.close()


def _read_snowflake(sql: str, params: tuple | list | None) -> pd.DataFrame:
    # Imported only when requested so Community Cloud does not need the connector.
    import sys

    infra = REPO_ROOT / "infra" / "snowflake"
    if str(infra) not in sys.path:
        sys.path.insert(0, str(infra))
    import sfconn

    env_file = REPO_ROOT / ".env.snowflake.local"
    if env_file.is_file():
        sfconn.read_env_file(env_file)

    snowflake_sql = sql.replace("?", "%s")
    try:
        con = sfconn.connect("lp-lens-app")
    except Exception as exc:
        raise RuntimeError(f"Snowflake connection failed: {sfconn.mask(exc)}") from None
    try:
        cur = con.cursor()
        cur.execute(snowflake_sql, params or [])
        columns = [c[0] for c in cur.description]
        rows = cur.fetchall()
    except Exception as exc:
        raise RuntimeError(f"Snowflake query failed: {sfconn.mask(exc)}") from None
    finally:
        con.close()

    frame = pd.DataFrame(rows, columns=columns)
    frame.columns = [c.lower() for c in frame.columns]
    return frame
