"""SELECT-only access to the performance marts.

Every ratio and rate is a column that dbt already computed. This module filters, joins
dimensions for labels, and orders rows. It does not divide, annualise, or average metrics.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd

from .connection import read_sql

_LATEST_PORTFOLIO = """
select
    p.investor_id,
    i.investor_name,
    i.investor_type,
    p.as_of_quarter,
    p.commitment_usd,
    p.fund_count,
    p.paid_in_usd,
    p.unfunded_usd,
    p.distributions_usd,
    p.nav_usd,
    p.dpi,
    p.rvpi,
    p.tvpi,
    p.net_irr,
    p.ks_pme,
    p.is_latest_quarter
from marts.fct_portfolio_performance_quarterly as p
inner join marts.dim_investor as i
    on p.investor_id = i.investor_id
where p.is_latest_quarter
order by p.commitment_usd desc, p.investor_id
"""

_LATEST_FUNDS = """
select
    f.fund_id,
    d.fund_name,
    d.strategy,
    s.strategy_group,
    d.vintage_year,
    d.fund_currency,
    m.manager_name,
    f.investor_id,
    i.investor_name,
    f.as_of_quarter,
    f.commitment_usd,
    f.paid_in_usd,
    f.unfunded_usd,
    f.distributions_usd,
    f.nav_usd,
    f.dpi,
    f.rvpi,
    f.tvpi,
    f.net_irr,
    f.ks_pme,
    f.fund_age_years,
    f.is_latest_quarter
from marts.fct_fund_performance_quarterly as f
inner join marts.dim_fund as d
    on f.fund_id = d.fund_id
inner join marts.dim_manager as m
    on d.manager_id = m.manager_id
inner join marts.dim_investor as i
    on f.investor_id = i.investor_id
inner join marts.dim_strategy as s
    on d.strategy = s.strategy_name
where f.is_latest_quarter
order by d.fund_name, f.investor_id
"""

_JCURVE = """
select
    f.fund_id,
    f.investor_id,
    f.as_of_quarter,
    f.fund_age_years,
    f.paid_in_usd,
    f.distributions_usd,
    f.nav_usd,
    f.dpi,
    f.rvpi,
    f.tvpi,
    f.net_irr
from marts.fct_fund_performance_quarterly as f
where f.fund_id = ?
  and f.investor_id = ?
order by f.as_of_quarter
"""

_AS_OF = """
select max(as_of_quarter) as as_of_quarter
from marts.fct_portfolio_performance_quarterly
where is_latest_quarter
"""


def _as_dates(frame: pd.DataFrame) -> pd.DataFrame:
    if "as_of_quarter" in frame.columns:
        frame = frame.copy()
        frame["as_of_quarter"] = pd.to_datetime(frame["as_of_quarter"]).dt.date
    return frame


def latest_portfolio_performance() -> pd.DataFrame:
    """One row per investor: the latest portfolio-mart snapshot. Metrics are mart columns."""
    return _as_dates(read_sql(_LATEST_PORTFOLIO))


def latest_fund_performance() -> pd.DataFrame:
    """One row per fund x investor at that position's latest quarter. Metrics are mart columns."""
    return _as_dates(read_sql(_LATEST_FUNDS))


def fund_jcurve(fund_id: str, investor_id: str) -> pd.DataFrame:
    """The fund-mart time series for one position. TVPI in the result is the mart's TVPI."""
    return _as_dates(read_sql(_JCURVE, (fund_id, investor_id)))


def fund_explorer() -> pd.DataFrame:
    """Same grain as latest_fund_performance; named for the explorer page."""
    return latest_fund_performance()


def as_of_quarter() -> dt.date | None:
    """Latest reporting date present on a latest-quarter portfolio row. Not a computed metric."""
    frame = read_sql(_AS_OF)
    if frame.empty or frame["as_of_quarter"].isna().all():
        return None
    value = frame["as_of_quarter"].iloc[0]
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    return pd.to_datetime(value).date()
