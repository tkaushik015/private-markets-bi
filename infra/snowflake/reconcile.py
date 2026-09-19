"""Cell-by-cell reconciliation of one schema between DuckDB and Snowflake.

Adapted from C0k11/quantai infra/snowflake/reconcile.py (MIT). Docstring and comments translated
from Chinese, query tag renamed, file reformatted by ruff. The comparison arithmetic is unchanged.
Two behavioural edits: the schema is a --schema argument rather than a hard-coded "marts", so the
script is not tied to a mart set that does not exist yet; and the two zips now state strict=
explicitly, which tightens the per-cell zip to raise on a length mismatch that the column check
upstream of it already rules out.

One raw snapshot, one dbt project, two engines: every table in the schema must match on name,
columns, row count and values. Two layers of comparison:

1. Column fingerprints: each column's values sorted and digested (numbers first rounded to 9
   significant digits), which shows at a glance which column disagrees.
2. Cell by cell: both sides sorted into the same row order, then compared position by position.
   Integers (including integral Decimals) must be exactly equal. Floats use a relative tolerance of
   1e-9, with an absolute 1e-12 for values near zero, because the two engines aggregate in different
   orders and the last digit can differ.

The verdict comes from the cell comparison. A column whose fingerprint differs only because of
where the 9-significant-digit rounding fell is reported separately and does not count as a
difference.

Usage:
    python infra/snowflake/reconcile.py --duckdb <path/to/lp_lens.duckdb> --env-file .env.snowflake.local
    python infra/snowflake/reconcile.py --duckdb <path> --schema marts
    python infra/snowflake/reconcile.py --negative-control --duckdb <path>

Exit code: 0 if everything matches (or the negative control correctly detects a changed cell),
1 if anything differs (or the negative control fails to notice).
"""

from __future__ import annotations

import argparse
import datetime as dt
import decimal
import hashlib
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import sfconn  # noqa: E402

REL_TOL = 1e-9
ABS_TOL = 1e-12


def norm(v):
    """Normalise a value from either driver into a comparable form.

    Integers and integral Decimals stay int so they compare exactly; other numbers become float.
    Dates, timestamps, booleans and strings get a type prefix so a string never collides with a
    date that happens to have the same text.
    """
    if v is None:
        return None
    if isinstance(v, bool):
        return f"b:{int(v)}"
    if isinstance(v, int):
        return v
    if isinstance(v, decimal.Decimal):
        if v.is_finite() and v == v.to_integral_value():
            return int(v)
        f = float(v)
        return None if math.isnan(f) else f
    if isinstance(v, float):
        return None if math.isnan(v) else v
    if isinstance(v, dt.datetime):
        return "t:" + v.replace(tzinfo=None).isoformat(sep=" ", timespec="microseconds")
    if isinstance(v, dt.date):
        return "d:" + v.isoformat()
    return "s:" + str(v)


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _sig(f: float) -> float:
    return float(f"{f:.9g}") + 0.0  # the + 0.0 folds -0.0 into 0.0


def _key(row: tuple) -> tuple:
    # Integers sort on their exact value, floats on 9 significant digits, so a last-digit
    # difference between engines cannot reorder the rows and cause a spurious mismatch.
    return tuple(
        (0, 0) if v is None else (1, v) if isinstance(v, int) else (1, _sig(v)) if isinstance(v, float) else (2, v)
        for v in row
    )


def fingerprint(values: list) -> str:
    items = sorted("~" if v is None else repr(_sig(float(v))) if _is_num(v) else v for v in values)
    return hashlib.md5("\x1f".join(items).encode("utf-8")).hexdigest()[:12]


def cells_equal(a, b) -> tuple[bool, float]:
    """Return (equal, relative difference). Integers compare exactly; tolerance applies only to floats."""
    if isinstance(a, int) and isinstance(b, int):
        return a == b, 0.0
    if _is_num(a) and _is_num(b):
        fa, fb = float(a), float(b)
        if not math.isclose(fa, fb, rel_tol=REL_TOL, abs_tol=ABS_TOL):
            return False, 0.0
        rel = abs(fa - fb) / max(abs(fa), abs(fb)) if fa != fb and fa != 0.0 and fb != 0.0 else 0.0
        return True, rel
    return a == b, 0.0


def compare_table(name: str, duck_cols, duck_rows, snow_cols, snow_rows) -> dict:
    res = {
        "table": name,
        "rows": (len(duck_rows), len(snow_rows)),
        "problems": [],
        "fingerprints_equal": (0, 0),
        "columns_mismatched": [],
        "max_rel_diff": 0.0,
    }
    dc = [c.lower() for c in duck_cols]
    sc = [c.lower() for c in snow_cols]
    if set(dc) != set(sc):
        res["problems"].append(
            f"columns differ: only duckdb {sorted(set(dc) - set(sc))}, only snowflake {sorted(set(sc) - set(dc))}"
        )
        return res
    order = [sc.index(c) for c in dc]
    d = [tuple(norm(v) for v in r) for r in duck_rows]
    s = [tuple(norm(r[i]) for i in order) for r in snow_rows]
    if len(d) != len(s):
        res["problems"].append(f"row count {len(d)} vs {len(s)}")
    equal_fp = sum(fingerprint([r[j] for r in d]) == fingerprint([r[j] for r in s]) for j in range(len(dc)))
    res["fingerprints_equal"] = (equal_fp, len(dc))
    d.sort(key=_key)
    s.sort(key=_key)
    bad_cols: set[str] = set()
    bad_cells = 0
    # strict=False on the rows: a row count mismatch is already recorded as a problem above, and
    # comparing the overlap still shows which columns drifted. strict=True on the cells, because
    # the column sets were proven equal above, so a length mismatch there would be a real bug.
    for rd, rs in zip(d, s, strict=False):
        for j, (a, b) in enumerate(zip(rd, rs, strict=True)):
            ok, rel = cells_equal(a, b)
            if not ok:
                bad_cells += 1
                bad_cols.add(dc[j])
            else:
                res["max_rel_diff"] = max(res["max_rel_diff"], rel)
    res["columns_mismatched"] = sorted(bad_cols)
    if bad_cells:
        res["problems"].append(f"{bad_cells} cells differ in {sorted(bad_cols)}")
    return res


def duckdb_tables(path: Path, schema: str) -> dict:
    import duckdb

    con = duckdb.connect(str(path), read_only=True)
    try:
        names = [
            r[0]
            for r in con.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = ? ORDER BY 1",
                [schema],
            ).fetchall()
        ]
        out = {}
        for n in names:
            cur = con.execute(f"SELECT * FROM {schema}.{n}")
            out[n.lower()] = ([c[0] for c in cur.description], cur.fetchall())
        return out
    finally:
        con.close()


def snowflake_tables(schema: str) -> dict:
    con = sfconn.connect("lp-lens-reconcile")
    try:
        cur = con.cursor()
        cur.execute(f"SHOW TABLES IN SCHEMA {schema}")
        names = sorted(r[1] for r in cur.fetchall())
        out = {}
        for n in names:
            cur.execute(f"SELECT * FROM {schema}.{n}")
            out[n.lower()] = ([c[0] for c in cur.description], cur.fetchall())
        return out
    finally:
        con.close()


def perturb_one_numeric_cell(cols: list[str], rows: list[tuple]) -> tuple[list[tuple], str, int]:
    """Return (rows with one numeric cell changed, column name, row index).

    Used by the negative control: a comparison that cannot fail is worthless. Changing a
    single already-nonzero number by 10% is enough to trip the 1e-9 relative check, and
    small enough that it cannot be an accidental empty-table case.
    """
    if not rows:
        raise SystemExit("negative control needs at least one row")
    for col_idx, _name in enumerate(cols):
        for row_idx, row in enumerate(rows):
            value = norm(row[col_idx])
            if isinstance(value, int) and value != 0:
                new = list(row)
                new[col_idx] = value + 1
                return [tuple(new) if i == row_idx else r for i, r in enumerate(rows)], cols[col_idx], row_idx
            if isinstance(value, float) and value != 0.0:
                new = list(row)
                new[col_idx] = value * 1.10
                return [tuple(new) if i == row_idx else r for i, r in enumerate(rows)], cols[col_idx], row_idx
    raise SystemExit("negative control could not find a nonzero numeric cell to perturb")


def run_negative_control(duck: dict) -> int:
    """Prove compare_table reports a single changed cell. Returns 0 on detection, 1 if not."""
    if not duck:
        print("[negative-control] no tables to perturb")
        return 1
    name = next(iter(sorted(duck)))
    cols, rows = duck[name]
    perturbed, column, row_idx = perturb_one_numeric_cell(cols, rows)
    result = compare_table(name, cols, rows, cols, perturbed)
    detected = bool(result["problems"]) and column.lower() in {c.lower() for c in result["columns_mismatched"]}
    print(
        f"[negative-control] {name}.{column} row {row_idx}: {'caught' if detected else 'MISSED'} ({result['problems']})"
    )
    return 0 if detected else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--duckdb", type=Path, required=True, help="DuckDB file built from the same raw snapshot")
    p.add_argument("--schema", default="marts", help="schema to reconcile on both engines (default: marts)")
    p.add_argument("--env-file", type=Path, help="KEY=VALUE file, e.g. .env.snowflake.local")
    p.add_argument(
        "--negative-control",
        action="store_true",
        help="perturb one cell of the DuckDB side against itself and require a DIFF (no Snowflake)",
    )
    args = p.parse_args(argv)
    if args.env_file:
        sfconn.read_env_file(args.env_file)

    duck = duckdb_tables(args.duckdb, args.schema)
    if args.negative_control:
        return run_negative_control(duck)

    try:
        snow = snowflake_tables(args.schema)
    except Exception as exc:
        # Broad on purpose: driver errors can echo the account identifier and key path, so every
        # failure mode has to reach the user masked. "from None" drops the original traceback,
        # which would reprint the unmasked text.
        raise SystemExit(f"[reconcile] could not read Snowflake: {sfconn.mask(exc)}") from None

    failed = 0
    if set(duck) != set(snow):
        failed += 1
        only_duck = sorted(set(duck) - set(snow))
        only_snow = sorted(set(snow) - set(duck))
        print(f"[table set] only duckdb {only_duck}, only snowflake {only_snow}")
    total_rows = total_cols = 0
    for name in sorted(set(duck) & set(snow)):
        r = compare_table(name, *duck[name], *snow[name])
        total_rows += r["rows"][0]
        total_cols += r["fingerprints_equal"][1]
        fp_eq, fp_n = r["fingerprints_equal"]
        status = "OK  " if not r["problems"] else "DIFF"
        print(
            f"[{status}] {name:<24} rows {r['rows'][0]:>7} / {r['rows'][1]:<7} "
            f"column fingerprints {fp_eq}/{fp_n}  max float rel diff {r['max_rel_diff']:.1e}"
        )
        for prob in r["problems"]:
            print(f"        {prob}")
        failed += bool(r["problems"])
    print(
        f"[reconcile] schema {args.schema}: {len(set(duck) & set(snow))} tables, {total_rows} rows, "
        f"{total_cols} columns; {'all equal' if not failed else f'{failed} with differences'}"
    )
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
