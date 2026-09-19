"""Parquet output with an explicit schema per table.

Three things here exist specifically to make the output byte-reproducible:

1. **Explicit schemas.** Types are declared, not inferred. Inference would let an empty or
   all-integral float column land as int64 in one run and double in another.
2. **Metadata stripped.** `pa.Table.from_pandas` attaches a pandas metadata blob that records the
   pandas version, so the same data written by two different pandas builds would differ. Dropping
   it makes the file depend on the data alone.
3. **Fixed write options.** Compression and format version are pinned rather than left to the
   pyarrow default, which can move between releases.

Row order is fixed by the callers, which sort every table by its primary key before writing.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

# Column order here is the column order in the file.
TABLE_SCHEMAS: dict[str, pa.Schema] = {
    "managers": pa.schema(
        [
            ("manager_id", pa.string()),
            ("name", pa.string()),
            ("hq_region", pa.string()),
            ("founded_year", pa.int16()),
        ]
    ),
    "funds": pa.schema(
        [
            ("fund_id", pa.string()),
            ("manager_id", pa.string()),
            ("fund_name", pa.string()),
            ("strategy", pa.string()),
            ("vintage_year", pa.int16()),
            ("currency", pa.string()),
            ("fund_size", pa.float64()),
            ("geography_focus", pa.string()),
        ]
    ),
    "investors": pa.schema(
        [
            ("investor_id", pa.string()),
            ("name", pa.string()),
            ("investor_type", pa.string()),
        ]
    ),
    "commitments": pa.schema(
        [
            ("commitment_id", pa.string()),
            ("investor_id", pa.string()),
            ("fund_id", pa.string()),
            ("commitment_amount", pa.float64()),
            ("commitment_date", pa.date32()),
        ]
    ),
    "cash_flows": pa.schema(
        [
            ("cash_flow_id", pa.string()),
            ("fund_id", pa.string()),
            ("investor_id", pa.string()),
            ("flow_date", pa.date32()),
            ("flow_type", pa.string()),
            ("amount", pa.float64()),
            ("currency", pa.string()),
        ]
    ),
    "nav": pa.schema(
        [
            ("fund_id", pa.string()),
            ("investor_id", pa.string()),
            ("quarter_end", pa.date32()),
            ("nav", pa.float64()),
            ("currency", pa.string()),
        ]
    ),
    "fx_rates": pa.schema(
        [
            ("rate_date", pa.date32()),
            ("from_currency", pa.string()),
            ("to_currency", pa.string()),
            ("rate", pa.float64()),
        ]
    ),
    "public_index": pa.schema(
        [
            ("index_date", pa.date32()),
            ("index_name", pa.string()),
            ("level", pa.float64()),
        ]
    ),
}

TABLE_ORDER: tuple[str, ...] = tuple(TABLE_SCHEMAS)


def to_arrow(name: str, frame: pd.DataFrame) -> pa.Table:
    """Convert one table to Arrow under its declared schema, with no pandas metadata attached."""
    try:
        schema = TABLE_SCHEMAS[name]
    except KeyError as exc:
        raise ValueError(f"no schema declared for table {name!r}; add one to TABLE_SCHEMAS") from exc
    ordered = frame[[field.name for field in schema]]
    return pa.Table.from_pandas(ordered, schema=schema, preserve_index=False).replace_schema_metadata(None)


def write_dataset(tables: dict[str, pd.DataFrame], out_dir: str | Path) -> dict[str, Path]:
    """Write every table to `out_dir` as `<name>.parquet`. Returns the paths written."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    for name in TABLE_ORDER:
        if name not in tables:
            raise ValueError(f"table {name!r} missing from the generated dataset")
        path = out / f"{name}.parquet"
        pq.write_table(
            to_arrow(name, tables[name]),
            path,
            compression="snappy",
            version="2.6",
            write_statistics=True,
        )
        written[name] = path
    return written


def file_hashes(out_dir: str | Path) -> dict[str, str]:
    """SHA-256 of each written Parquet file, for the determinism check."""
    out = Path(out_dir)
    hashes: dict[str, str] = {}
    for name in TABLE_ORDER:
        path = out / f"{name}.parquet"
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes
