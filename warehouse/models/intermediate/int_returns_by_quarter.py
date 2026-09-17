"""Net IRR and KS-PME per fund x investor x quarter end.

A Python model because IRR has no closed form. Solving it in SQL would mean either a recursive CTE
implementing Newton's method or a hard-coded approximation, and both would be a second
implementation of arithmetic that already exists and is tested. This model imports
`lp_lens.metrics.returns` -- the same module the reconciliation tests call -- so there is exactly
one definition of IRR and PME in the project.

What it computes, per position and per quarter:

- **net_irr**: IRR over every flow up to and including that quarter, with residual NAV appended as
  a positive flow on the quarter-end date. Net to the LP in the sense that management fees are
  included as paid-in; see the mart docs for what "net" does and does not cover here.
- **ks_pme**: the same flows future-valued on the public index, with NAV added undiscounted.

Both are NULL where they cannot be computed -- a position that has only ever paid in has no IRR,
and NULL is the honest answer rather than zero.

Returned as pandas nullable Float64 so a missing value lands in DuckDB as NULL rather than as NaN.
A NaN would satisfy a not-null test and then read as a number downstream, which is the failure
mode this whole file is trying to avoid.
"""

from __future__ import annotations

import pandas as pd

from lp_lens.metrics.returns import build_lp_flow_vector, ks_pme, xirr


def compute_position_returns(
    spine: pd.DataFrame,
    flows: pd.DataFrame,
    nav: pd.DataFrame,
    index: pd.DataFrame,
) -> pd.DataFrame:
    """Return one row per (fund_id, investor_id, as_of_quarter) with net_irr and ks_pme."""
    index_by_date = dict(zip(index["index_date"], index["index_level"], strict=True))
    nav_by_key = {
        (fund_id, investor_id, quarter_end): nav_usd
        for fund_id, investor_id, quarter_end, nav_usd in zip(
            nav["fund_id"], nav["investor_id"], nav["quarter_end"], nav["nav_usd"], strict=True
        )
    }

    flows = flows.sort_values(["fund_id", "investor_id", "flow_date"])
    flows_by_pair = {key: group for key, group in flows.groupby(["fund_id", "investor_id"], sort=True)}

    records: list[dict] = []
    for (fund_id, investor_id), pair_spine in spine.groupby(["fund_id", "investor_id"], sort=True):
        pair_flows = flows_by_pair.get((fund_id, investor_id))
        flow_dates = list(pair_flows["flow_date"]) if pair_flows is not None else []
        flow_amounts = list(pair_flows["signed_amount_usd"]) if pair_flows is not None else []

        for quarter_end in sorted(pair_spine["quarter_end"]):
            # Inception-to-date: every flow on or before this quarter end, none after it.
            upto = [i for i, d in enumerate(flow_dates) if d <= quarter_end]
            position_nav = float(nav_by_key.get((fund_id, investor_id, quarter_end), 0.0) or 0.0)

            dates, amounts = build_lp_flow_vector(
                [flow_dates[i] for i in upto],
                [flow_amounts[i] for i in upto],
                as_of_date=quarter_end,
                nav=position_nav,
            )
            terminal_level = index_by_date[quarter_end]
            levels = [index_by_date[d] for d in dates[: len(upto)]]

            records.append(
                {
                    "fund_id": fund_id,
                    "investor_id": investor_id,
                    "as_of_quarter": quarter_end,
                    "net_irr": xirr(dates, amounts),
                    # NAV is passed separately and enters the numerator undiscounted, so only the
                    # real flows are future-valued -- hence levels is sliced to len(upto).
                    "ks_pme": ks_pme(
                        [flow_amounts[i] for i in upto],
                        levels,
                        nav=position_nav,
                        terminal_index_level=terminal_level,
                    ),
                }
            )

    frame = pd.DataFrame.from_records(records, columns=["fund_id", "investor_id", "as_of_quarter", "net_irr", "ks_pme"])
    frame["net_irr"] = pd.array(frame["net_irr"], dtype="Float64")
    frame["ks_pme"] = pd.array(frame["ks_pme"], dtype="Float64")
    return frame


def model(dbt, session):
    dbt.config(materialized="table")
    return compute_position_returns(
        spine=dbt.ref("int_quarter_spine").df(),
        flows=dbt.ref("int_cash_flows_usd").df(),
        nav=dbt.ref("int_nav_usd").df(),
        index=dbt.ref("stg_public_index").df(),
    )
