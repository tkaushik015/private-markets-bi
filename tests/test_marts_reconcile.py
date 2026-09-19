"""Reconciles the dbt marts against an independent pandas recomputation from the raw Parquet.

Two paths to the same numbers. The warehouse path does cumulative aggregation in SQL and calls
`lp_lens.metrics.returns` from a dbt Python model. This test does the aggregation again in pandas,
from the Parquet files, and calls the same returns module. What is shared is the IRR and PME
arithmetic, deliberately -- there should be exactly one implementation of those, and the project
rule is that no metric formula is duplicated. What is *not* shared is everything else: the currency
conversion, the quarter spine, the cumulative windows, the ratio denominators and the portfolio
pooling are all written twice, once in SQL and once here.

That is what makes the comparison worth running. An error in the SQL aggregation, the as-of
windowing or the sign convention shows up as a disagreement; an error in the IRR solver would not,
which is why the solver has its own tests in test_returns.py against independently computed values.

`test_negative_control_detects_a_perturbed_cash_flow` proves the comparison can actually fail.
Without it, a reconciliation that silently compared a frame to itself would pass just as happily.
"""

from __future__ import annotations

import datetime as dt
import os
import shutil
from pathlib import Path

import pandas as pd
import pytest

from lp_lens.generate import generate_dataset, load_config, write_dataset
from lp_lens.metrics.returns import build_lp_flow_vector, ks_pme, xirr

REPO_ROOT = Path(__file__).resolve().parents[1]
WAREHOUSE_DIR = REPO_ROOT / "warehouse"
CONFIG_PATH = REPO_ROOT / "configs" / "generator.yaml"

PAID_IN_TYPES = ("capital_call", "management_fee")
DISTRIBUTION_TYPES = ("distribution", "recallable_distribution")
QUARTER_END_MONTH_DAY = ((3, 31), (6, 30), (9, 30), (12, 31))

RELATIVE_TOLERANCE = 1e-9


# ------------------------------------------------------------------------------------------------
# Building the warehouse
# ------------------------------------------------------------------------------------------------


@pytest.fixture(scope="session")
def built_warehouse(tmp_path_factory: pytest.TempPathFactory) -> dict:
    """Generate raw Parquet and run `dbt build` against a throwaway DuckDB file.

    Generating the data here rather than relying on `data/raw/` existing means the test is
    self-contained: it never reads a file a developer might have left in a modified state, and CI
    does not depend on step ordering.
    """
    from dbt.cli.main import dbtRunner

    root = tmp_path_factory.mktemp("reconcile")
    raw_dir = root / "raw"
    db_path = root / "lp_lens.duckdb"

    config = load_config(CONFIG_PATH)
    write_dataset(generate_dataset(config), raw_dir)

    os.environ["LP_LENS_RAW_DIR"] = str(raw_dir)
    os.environ["LP_LENS_DB_PATH"] = str(db_path)

    result = dbtRunner().invoke(
        [
            "build",
            "--project-dir",
            str(WAREHOUSE_DIR),
            "--profiles-dir",
            str(WAREHOUSE_DIR),
            "--target",
            "local",
            "--no-partial-parse",
        ]
    )
    assert result.success, f"dbt build failed: {result.exception}"

    # Read from a copy rather than the file dbt just wrote. dbtRunner leaves its read-write
    # connection open inside this process, and DuckDB refuses a second connection to the same file
    # under a different configuration. Copying also guarantees the tests below cannot be affected
    # by anything dbt does afterwards.
    snapshot = root / "lp_lens_snapshot.duckdb"
    shutil.copy2(db_path, snapshot)
    wal = db_path.with_suffix(db_path.suffix + ".wal")
    if wal.exists():
        shutil.copy2(wal, snapshot.with_suffix(snapshot.suffix + ".wal"))

    raw = {path.stem: pd.read_parquet(path) for path in sorted(raw_dir.glob("*.parquet"))}
    return {"raw": raw, "raw_dir": raw_dir, "db_path": snapshot, "config": config}


def _normalise_dates(frame: pd.DataFrame) -> pd.DataFrame:
    """Convert DuckDB DATE columns to `datetime.date` objects.

    DuckDB hands DATE back as datetime64[us] while pandas reads a Parquet date32 as
    `datetime.date`. Merging the two raises rather than silently mismatching, but the two sides
    have to agree before they can be compared at all.
    """
    for column in frame.columns:
        if pd.api.types.is_datetime64_any_dtype(frame[column]):
            frame[column] = frame[column].dt.date
    return frame


@pytest.fixture(scope="session")
def marts(built_warehouse: dict) -> dict[str, pd.DataFrame]:
    import duckdb

    con = duckdb.connect(str(built_warehouse["db_path"]), read_only=True)
    try:
        return {
            "fund": _normalise_dates(con.execute("select * from marts.fct_fund_performance_quarterly").df()),
            "portfolio": _normalise_dates(con.execute("select * from marts.fct_portfolio_performance_quarterly").df()),
        }
    finally:
        con.close()


# ------------------------------------------------------------------------------------------------
# The independent recomputation
# ------------------------------------------------------------------------------------------------


def quarter_ends_between(start: dt.date, end: dt.date) -> list[dt.date]:
    """Real quarter-end dates in [start, end]. Written from a literal month/day table so a
    quarter end is never an approximation of one."""
    out = []
    for year in range(start.year, end.year + 1):
        for month, day in QUARTER_END_MONTH_DAY:
            q = dt.date(year, month, day)
            if start <= q <= end:
                out.append(q)
    return out


def containing_quarter_end(date: dt.date) -> dt.date:
    for month, day in QUARTER_END_MONTH_DAY:
        q = dt.date(date.year, month, day)
        if date <= q:
            return q
    return dt.date(date.year, 12, 31)


def _prepare(raw: dict[str, pd.DataFrame]) -> dict:
    fx = raw["fx_rates"]
    fx = fx[(fx.from_currency == "EUR") & (fx.to_currency == "USD")]
    rate_by_date = dict(zip(fx.rate_date, fx.rate, strict=True))
    index_by_date = dict(zip(raw["public_index"].index_date, raw["public_index"].level, strict=True))
    currency_by_fund = dict(zip(raw["funds"].fund_id, raw["funds"].currency, strict=True))
    vintage_by_fund = dict(zip(raw["funds"].fund_id, raw["funds"].vintage_year, strict=True))

    flows = raw["cash_flows"].copy()
    flows["amount_usd"] = [
        amount * rate_by_date[date] if currency == "EUR" else amount
        for amount, currency, date in zip(flows.amount, flows.currency, flows.flow_date, strict=True)
    ]
    flows["direction"] = [-1 if t in PAID_IN_TYPES else 1 for t in flows.flow_type]
    flows["signed_usd"] = flows.direction * flows.amount_usd

    nav = raw["nav"].copy()
    nav["nav_usd"] = [
        value * rate_by_date[date] if currency == "EUR" else value
        for value, currency, date in zip(nav.nav, nav.currency, nav.quarter_end, strict=True)
    ]

    commitments = raw["commitments"].copy()
    commitments["commitment_usd"] = [
        amount * rate_by_date[date] if currency_by_fund[fund] == "EUR" else amount
        for amount, fund, date in zip(
            commitments.commitment_amount, commitments.fund_id, commitments.commitment_date, strict=True
        )
    ]

    as_of = max(fx.rate_date)
    return {
        "flows": flows,
        "nav": nav,
        "commitments": commitments,
        "index_by_date": index_by_date,
        "vintage_by_fund": vintage_by_fund,
        "as_of": as_of,
    }


def expected_fund_performance(raw: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Recompute fct_fund_performance_quarterly in pandas, from the Parquet."""
    prepared = _prepare(raw)
    flows, nav, commitments = prepared["flows"], prepared["nav"], prepared["commitments"]
    index_by_date = prepared["index_by_date"]

    nav_by_key = {
        (f, i, q): v for f, i, q, v in zip(nav.fund_id, nav.investor_id, nav.quarter_end, nav.nav_usd, strict=True)
    }
    last_nav_quarter = nav.groupby(["fund_id", "investor_id"]).quarter_end.max().to_dict()
    commitment_by_pair = {
        (f, i): (c, a)
        for f, i, c, a in zip(
            commitments.fund_id,
            commitments.investor_id,
            commitments.commitment_usd,
            commitments.commitment_amount,
            strict=True,
        )
    }

    flows = flows.sort_values(["fund_id", "investor_id", "flow_date"])
    records = []
    for (fund_id, investor_id), group in flows.groupby(["fund_id", "investor_id"], sort=True):
        calls = group[group.flow_type == "capital_call"]
        if calls.empty:
            continue
        first_quarter = containing_quarter_end(calls.flow_date.min())
        end_quarter = last_nav_quarter.get((fund_id, investor_id), containing_quarter_end(prepared["as_of"]))

        dates = list(group.flow_date)
        signed = list(group.signed_usd)
        types = list(group.flow_type)
        amounts_usd = list(group.amount_usd)
        commitment_usd, commitment_local = commitment_by_pair[(fund_id, investor_id)]

        for quarter in quarter_ends_between(first_quarter, end_quarter):
            upto = [k for k, d in enumerate(dates) if d <= quarter]
            paid_in = sum(amounts_usd[k] for k in upto if types[k] in PAID_IN_TYPES)
            distributed = sum(amounts_usd[k] for k in upto if types[k] in DISTRIBUTION_TYPES)
            recallable = sum(amounts_usd[k] for k in upto if types[k] == "recallable_distribution")
            position_nav = float(nav_by_key.get((fund_id, investor_id, quarter), 0.0))

            irr_dates, irr_amounts = build_lp_flow_vector(
                [dates[k] for k in upto], [signed[k] for k in upto], as_of_date=quarter, nav=position_nav
            )
            records.append(
                {
                    "fund_id": fund_id,
                    "investor_id": investor_id,
                    "as_of_quarter": quarter,
                    "commitment_usd": commitment_usd,
                    "paid_in_usd": paid_in,
                    "distributions_usd": distributed,
                    "unfunded_usd": commitment_usd + recallable - paid_in,
                    "nav_usd": position_nav,
                    "dpi": distributed / paid_in if paid_in > 0 else None,
                    "rvpi": position_nav / paid_in if paid_in > 0 else None,
                    "tvpi": (distributed + position_nav) / paid_in if paid_in > 0 else None,
                    "net_irr": xirr(irr_dates, irr_amounts),
                    "ks_pme": ks_pme(
                        [signed[k] for k in upto],
                        [index_by_date[dates[k]] for k in upto],
                        nav=position_nav,
                        terminal_index_level=index_by_date[quarter],
                    ),
                    "commitment_local": commitment_local,
                    "fund_age_years": (quarter - dt.date(prepared["vintage_by_fund"][fund_id], 1, 1)).days / 365.25,
                }
            )
    return pd.DataFrame.from_records(records)


def expected_portfolio_performance(raw: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Recompute fct_portfolio_performance_quarterly in pandas, from the Parquet.

    Built from the flows rather than by aggregating the fund-level expectation, mirroring the
    reason the mart is: a liquidated fund has no fund-level row at a later quarter, and its history
    must still sit in the investor's inception-to-date totals.
    """
    prepared = _prepare(raw)
    flows, nav, commitments = prepared["flows"], prepared["nav"], prepared["commitments"]
    index_by_date = prepared["index_by_date"]

    fund_expected = expected_fund_performance(raw)
    quarters_by_investor = fund_expected.groupby("investor_id").as_of_quarter.unique().to_dict()

    nav_by_investor_quarter = nav.groupby(["investor_id", "quarter_end"]).nav_usd.sum().to_dict()
    flows = flows.sort_values(["investor_id", "flow_date"])

    records = []
    for investor_id, group in flows.groupby("investor_id", sort=True):
        dates = list(group.flow_date)
        signed = list(group.signed_usd)
        types = list(group.flow_type)
        amounts_usd = list(group.amount_usd)
        investor_commitments = commitments[commitments.investor_id == investor_id]

        for quarter in sorted(quarters_by_investor[investor_id]):
            upto = [k for k, d in enumerate(dates) if d <= quarter]
            paid_in = sum(amounts_usd[k] for k in upto if types[k] in PAID_IN_TYPES)
            distributed = sum(amounts_usd[k] for k in upto if types[k] in DISTRIBUTION_TYPES)
            recallable = sum(amounts_usd[k] for k in upto if types[k] == "recallable_distribution")
            pooled_nav = float(nav_by_investor_quarter.get((investor_id, quarter), 0.0))
            signed_so_far = investor_commitments[investor_commitments.commitment_date <= quarter]
            commitment_usd = float(signed_so_far.commitment_usd.sum())

            irr_dates, irr_amounts = build_lp_flow_vector(
                [dates[k] for k in upto], [signed[k] for k in upto], as_of_date=quarter, nav=pooled_nav
            )
            records.append(
                {
                    "investor_id": investor_id,
                    "as_of_quarter": quarter,
                    "commitment_usd": commitment_usd,
                    "fund_count": len(signed_so_far),
                    "paid_in_usd": paid_in,
                    "distributions_usd": distributed,
                    "unfunded_usd": commitment_usd + recallable - paid_in,
                    "nav_usd": pooled_nav,
                    "dpi": distributed / paid_in if paid_in > 0 else None,
                    "rvpi": pooled_nav / paid_in if paid_in > 0 else None,
                    "tvpi": (distributed + pooled_nav) / paid_in if paid_in > 0 else None,
                    "net_irr": xirr(irr_dates, irr_amounts),
                    "ks_pme": ks_pme(
                        [signed[k] for k in upto],
                        [index_by_date[dates[k]] for k in upto],
                        nav=pooled_nav,
                        terminal_index_level=index_by_date[quarter],
                    ),
                }
            )
    return pd.DataFrame.from_records(records)


# ------------------------------------------------------------------------------------------------
# Comparison helpers
# ------------------------------------------------------------------------------------------------


def _mismatches(actual: pd.DataFrame, expected: pd.DataFrame, keys: list[str], columns: list[str]) -> pd.DataFrame:
    """Rows where any compared column disagrees beyond the relative tolerance.

    NULL is compared as a value, not skipped: a NULL on one side and a number on the other is a
    disagreement, and it is exactly the disagreement an IRR that silently became 0.0 would cause.
    """
    merged = actual.merge(expected, on=keys, how="outer", suffixes=("_actual", "_expected"), indicator=True)
    bad = merged[merged["_merge"] != "both"].copy()
    bad["mismatched_columns"] = "row missing on one side"

    both = merged[merged["_merge"] == "both"]
    flags = pd.Series(False, index=both.index)
    per_row_columns: list[list[str]] = [[] for _ in range(len(both))]
    for column in columns:
        left = pd.to_numeric(both[f"{column}_actual"], errors="coerce")
        right = pd.to_numeric(both[f"{column}_expected"], errors="coerce")
        left_null, right_null = left.isna(), right.isna()
        scale = pd.concat([left.abs(), right.abs()], axis=1).max(axis=1).fillna(0.0)
        # Absolute floor so a value legitimately near zero is not judged on relative terms.
        differs = ((left - right).abs() > (RELATIVE_TOLERANCE * scale).clip(lower=1e-9)).fillna(False)
        column_bad = (left_null != right_null) | (~left_null & ~right_null & differs)
        for position, is_bad in enumerate(column_bad.to_numpy()):
            if is_bad:
                per_row_columns[position].append(column)
        flags = flags | column_bad

    failing = both[flags].copy()
    failing["mismatched_columns"] = [
        ", ".join(cols) for cols, is_bad in zip(per_row_columns, flags.to_numpy(), strict=True) if is_bad
    ]
    return pd.concat([bad, failing], ignore_index=True)


FUND_COLUMNS = [
    "commitment_usd",
    "paid_in_usd",
    "distributions_usd",
    "unfunded_usd",
    "nav_usd",
    "dpi",
    "rvpi",
    "tvpi",
    "net_irr",
    "ks_pme",
    "commitment_local",
    "fund_age_years",
]
PORTFOLIO_COLUMNS = [
    "commitment_usd",
    "fund_count",
    "paid_in_usd",
    "distributions_usd",
    "unfunded_usd",
    "nav_usd",
    "dpi",
    "rvpi",
    "tvpi",
    "net_irr",
    "ks_pme",
]


# ------------------------------------------------------------------------------------------------
# Reconciliation
# ------------------------------------------------------------------------------------------------


def test_fund_performance_reconciles_row_for_row(built_warehouse: dict, marts: dict) -> None:
    expected = expected_fund_performance(built_warehouse["raw"])
    actual = marts["fund"]
    assert len(actual) == len(expected), f"row count differs: mart {len(actual)}, recomputed {len(expected)}"

    failures = _mismatches(actual, expected, ["fund_id", "investor_id", "as_of_quarter"], FUND_COLUMNS)
    assert failures.empty, (
        f"{len(failures)} of {len(actual)} rows disagree. First few:\n"
        f"{failures.head(5)[['fund_id', 'investor_id', 'as_of_quarter', 'mismatched_columns']]}"
    )


def test_portfolio_performance_reconciles_row_for_row(built_warehouse: dict, marts: dict) -> None:
    expected = expected_portfolio_performance(built_warehouse["raw"])
    actual = marts["portfolio"]
    assert len(actual) == len(expected), f"row count differs: mart {len(actual)}, recomputed {len(expected)}"

    failures = _mismatches(actual, expected, ["investor_id", "as_of_quarter"], PORTFOLIO_COLUMNS)
    assert failures.empty, (
        f"{len(failures)} of {len(actual)} rows disagree. First few:\n"
        f"{failures.head(5)[['investor_id', 'as_of_quarter', 'mismatched_columns']]}"
    )


def test_sql_sign_convention_matches_the_python_one(marts: dict, built_warehouse: dict) -> None:
    """The sign rule exists twice -- a CASE in int_cash_flows_usd and FLOW_DIRECTION in Python.

    Two expressions of one rule can drift, so they are compared rather than trusted. This is the
    only place the duplication is acceptable, because SQL cannot import the Python dict.
    """
    import duckdb

    from lp_lens.generate import FLOW_DIRECTION

    con = duckdb.connect(str(built_warehouse["db_path"]), read_only=True)
    try:
        rows = con.execute(
            "select distinct flow_type, flow_direction from marts.fct_cash_flows order by flow_type"
        ).fetchall()
    finally:
        con.close()

    sql_directions = dict(rows)
    assert sql_directions == {k: v for k, v in FLOW_DIRECTION.items() if k in sql_directions}
    assert set(sql_directions) == set(FLOW_DIRECTION), (
        f"flow types in the mart {sorted(sql_directions)} differ from FLOW_DIRECTION {sorted(FLOW_DIRECTION)}"
    )


def test_no_metric_is_a_fabricated_zero(marts: dict) -> None:
    """An uncomputable IRR must be NULL, not 0.0, and must not have become NaN on the way through
    the Python model. NaN would pass a not-null test and then read as a number downstream."""
    for name, frame in (("fund", marts["fund"]), ("portfolio", marts["portfolio"])):
        for column in ("net_irr", "ks_pme"):
            values = frame[column]
            assert not (values == 0.0).any(), f"{name}.{column} contains an exact zero"
            non_null = values.dropna()
            assert not non_null.isin([float("inf"), float("-inf")]).any(), f"{name}.{column} contains an infinity"


# ------------------------------------------------------------------------------------------------
# Negative control
# ------------------------------------------------------------------------------------------------


def _perturb_middle_capital_call(raw_tables: dict[str, pd.DataFrame]) -> tuple[dict[str, pd.DataFrame], pd.Series]:
    """Copy the raw tables and overstate one capital call by 10%. Deterministic, not random."""
    raw = {name: frame.copy() for name, frame in raw_tables.items()}
    flows = raw["cash_flows"]
    calls = flows[flows.flow_type == "capital_call"].sort_values("cash_flow_id")
    target = calls.iloc[len(calls) // 2]
    flows.loc[flows.index[flows.cash_flow_id == target.cash_flow_id][0], "amount"] = float(target.amount) * 1.10
    return raw, target


def test_negative_control_detects_a_perturbed_cash_flow(built_warehouse: dict, marts: dict) -> None:
    """Perturb one capital call and confirm the reconciliation fails on exactly the rows it should.

    A reconciliation that cannot fail is worthless, so this drives one deliberate error through it.
    The assertion is not merely that something broke: it is that the mismatched rows are exactly
    the position's quarters from the perturbed flow onward, and no others. Too few rows would mean
    the comparison is insensitive; too many would mean it leaks across positions.

    The portfolio mart must fail as well. It is built from the same cash flows, so that
    investor's inception-to-date totals from the perturbed quarter onward include the overstated
    call. Checking only the fund mart would let a portfolio comparison that compared a frame to
    itself pass unnoticed.
    """
    raw, target = _perturb_middle_capital_call(built_warehouse["raw"])
    affected_quarter = containing_quarter_end(target.flow_date)

    fund_failures = _mismatches(
        marts["fund"], expected_fund_performance(raw), ["fund_id", "investor_id", "as_of_quarter"], FUND_COLUMNS
    )
    assert not fund_failures.empty, "perturbing a capital flow did not break the fund reconciliation at all"

    expected_fund = {
        (target.fund_id, target.investor_id, quarter)
        for quarter in marts["fund"]
        .loc[
            (marts["fund"].fund_id == target.fund_id) & (marts["fund"].investor_id == target.investor_id),
            "as_of_quarter",
        ]
        .tolist()
        if quarter >= affected_quarter
    }
    actual_fund = set(zip(fund_failures.fund_id, fund_failures.investor_id, fund_failures.as_of_quarter, strict=True))
    assert actual_fund == expected_fund, (
        f"fund mart: expected exactly the {len(expected_fund)} quarters of "
        f"{target.fund_id}/{target.investor_id} from {affected_quarter} onward to fail, "
        f"got {len(actual_fund)}. "
        f"Unexpected: {sorted(actual_fund - expected_fund)[:5]}. "
        f"Missing: {sorted(expected_fund - actual_fund)[:5]}"
    )

    portfolio_failures = _mismatches(
        marts["portfolio"],
        expected_portfolio_performance(raw),
        ["investor_id", "as_of_quarter"],
        PORTFOLIO_COLUMNS,
    )
    assert not portfolio_failures.empty, (
        "perturbing a capital flow did not break the portfolio reconciliation; "
        "the investor that owns the position must move"
    )

    expected_portfolio = {
        (target.investor_id, quarter)
        for quarter in marts["portfolio"].loc[marts["portfolio"].investor_id == target.investor_id, "as_of_quarter"]
        if quarter >= affected_quarter
    }
    actual_portfolio = set(zip(portfolio_failures.investor_id, portfolio_failures.as_of_quarter, strict=True))
    assert actual_portfolio == expected_portfolio, (
        f"portfolio mart: expected exactly the {len(expected_portfolio)} quarters of "
        f"{target.investor_id} from {affected_quarter} onward to fail, "
        f"got {len(actual_portfolio)}. "
        f"Unexpected: {sorted(actual_portfolio - expected_portfolio)[:5]}. "
        f"Missing: {sorted(expected_portfolio - actual_portfolio)[:5]}"
    )


def test_negative_control_leaves_other_positions_untouched(built_warehouse: dict, marts: dict) -> None:
    """The other side of the same control: a perturbation must not disturb positions it has nothing
    to do with. Together with the test above this bounds the comparison from both directions."""
    raw, target = _perturb_middle_capital_call(built_warehouse["raw"])

    fund_failures = _mismatches(
        marts["fund"], expected_fund_performance(raw), ["fund_id", "investor_id", "as_of_quarter"], FUND_COLUMNS
    )
    other_pairs = {(f, i) for f, i in zip(fund_failures.fund_id, fund_failures.investor_id, strict=True)} - {
        (target.fund_id, target.investor_id)
    }
    assert not other_pairs, f"the perturbation leaked into unrelated fund positions: {sorted(other_pairs)[:5]}"

    portfolio_failures = _mismatches(
        marts["portfolio"],
        expected_portfolio_performance(raw),
        ["investor_id", "as_of_quarter"],
        PORTFOLIO_COLUMNS,
    )
    other_investors = set(portfolio_failures.investor_id) - {target.investor_id}
    assert not other_investors, (
        f"the perturbation leaked into unrelated investors' portfolio rows: {sorted(other_investors)[:5]}"
    )


def test_null_irr_is_compared_not_skipped(built_warehouse: dict, marts: dict) -> None:
    """NULL IRR is a value the reconciliation must agree on, not a row it may drop.

    `_mismatches` treats NULL vs NULL as agreement and NULL vs a number as a failure. Replacing
    the mart's NULL IRRs with 0.0 must therefore light up exactly those rows -- the failure mode
    the honesty rule exists to catch, a silent 'broke even' in place of 'could not be computed'.
    """
    expected = expected_fund_performance(built_warehouse["raw"])
    actual_null_keys = {
        (row.fund_id, row.investor_id, row.as_of_quarter)
        for row in marts["fund"].loc[marts["fund"].net_irr.isna()].itertuples(index=False)
    }
    expected_null_keys = {
        (row.fund_id, row.investor_id, row.as_of_quarter)
        for row in expected.loc[expected.net_irr.isna()].itertuples(index=False)
    }
    assert actual_null_keys == expected_null_keys, (
        f"NULL IRR keys disagree. mart {sorted(actual_null_keys)[:5]}, recomputed {sorted(expected_null_keys)[:5]}"
    )
    assert actual_null_keys, "this seed is expected to produce at least one uncomputable IRR"

    fabricated = marts["fund"].copy()
    fabricated.loc[fabricated.net_irr.isna(), "net_irr"] = 0.0
    failures = _mismatches(fabricated, expected, ["fund_id", "investor_id", "as_of_quarter"], FUND_COLUMNS)
    failed_keys = set(zip(failures.fund_id, failures.investor_id, failures.as_of_quarter, strict=True))
    assert actual_null_keys <= failed_keys, (
        f"replacing NULL IRR with 0.0 did not fail those rows; missed {sorted(actual_null_keys - failed_keys)}"
    )
