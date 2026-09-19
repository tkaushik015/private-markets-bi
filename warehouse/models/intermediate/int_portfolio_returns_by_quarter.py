"""Net IRR and KS-PME per investor x quarter end, on pooled cash flows.

A second Python model rather than an aggregation of `int_returns_by_quarter`, because a portfolio
IRR is **not** any average of its funds' IRRs. IRR is not additive: averaging fund rates, even
weighted by paid-in, gives a number that no cash flow stream would ever produce. The only correct
portfolio IRR is the one solved over every flow of every position pooled into a single vector,
which is what this does.

The same holds for the ratios in the mart above it: those are ratios of summed amounts, never
averages of fund ratios.
"""

from __future__ import annotations

import os

import pandas as pd

# dbt.config() arguments must be Python literals. The Snowpark wheel path is in schema.yml.


def compute_portfolio_returns(
    spine: pd.DataFrame,
    flows: pd.DataFrame,
    nav: pd.DataFrame,
    index: pd.DataFrame,
) -> pd.DataFrame:
    """Return one row per (investor_id, as_of_quarter) with pooled net_irr and ks_pme."""
    from lp_lens.metrics.returns import build_lp_flow_vector, ks_pme, xirr

    index_by_date = dict(zip(index["index_date"], index["index_level"], strict=True))

    flows = flows.sort_values(["investor_id", "flow_date"])
    flows_by_investor = {key: group for key, group in flows.groupby("investor_id", sort=True)}
    # NAV pooled across the investor's funds at each quarter end. A fund that liquidated earlier
    # simply has no row here, which is the same thing as contributing zero residual value.
    nav_by_investor_quarter = nav.groupby(["investor_id", "quarter_end"])["nav_usd"].sum().to_dict()

    records: list[dict] = []
    for investor_id, investor_spine in spine.groupby("investor_id", sort=True):
        investor_flows = flows_by_investor.get(investor_id)
        flow_dates = list(investor_flows["flow_date"]) if investor_flows is not None else []
        flow_amounts = list(investor_flows["signed_amount_usd"]) if investor_flows is not None else []

        for quarter_end in sorted(set(investor_spine["quarter_end"])):
            upto = [i for i, d in enumerate(flow_dates) if d <= quarter_end]
            pooled_nav = float(nav_by_investor_quarter.get((investor_id, quarter_end), 0.0) or 0.0)

            dates, amounts = build_lp_flow_vector(
                [flow_dates[i] for i in upto],
                [flow_amounts[i] for i in upto],
                as_of_date=quarter_end,
                nav=pooled_nav,
            )
            levels = [index_by_date[d] for d in dates[: len(upto)]]

            records.append(
                {
                    "investor_id": investor_id,
                    "as_of_quarter": quarter_end,
                    "net_irr": xirr(dates, amounts),
                    "ks_pme": ks_pme(
                        [flow_amounts[i] for i in upto],
                        levels,
                        nav=pooled_nav,
                        terminal_index_level=index_by_date[quarter_end],
                    ),
                }
            )

    frame = pd.DataFrame.from_records(records, columns=["investor_id", "as_of_quarter", "net_irr", "ks_pme"])
    frame["net_irr"] = pd.array(frame["net_irr"], dtype="Float64")
    frame["ks_pme"] = pd.array(frame["ks_pme"], dtype="Float64")
    return frame


def model(dbt, session):
    dbt.config(materialized="table")
    module = type(session).__module__ if session is not None else ""
    if "snowpark" in module and not os.environ.get("LP_LENS_SNOWPARK_WHEEL", "").strip():
        raise RuntimeError(
            "LP_LENS_SNOWPARK_WHEEL is unset. Stage the slim metrics wheel with "
            "`python infra/snowflake/load_raw.py --stage-wheel` and set the variable "
            "to @<database>.RAW.LP_LENS_PACKAGES/lp_lens-0.1.0-py3-none-any.whl"
        )
    return compute_portfolio_returns(
        spine=dbt.ref("int_quarter_spine").df(),
        flows=dbt.ref("int_cash_flows_usd").df(),
        nav=dbt.ref("int_nav_usd").df(),
        index=dbt.ref("stg_public_index").df(),
    )
