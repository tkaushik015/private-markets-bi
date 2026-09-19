"""Read-only query layer over the dbt marts.

Nothing here recomputes IRR, TVPI, DPI, RVPI or PME. Every metric column is selected from
`fct_fund_performance_quarterly` or `fct_portfolio_performance_quarterly`. The app and the
tests share this module so a chart cannot silently grow its own formula.
"""

from .connection import DEMO_DB, active_source, read_sql
from .docs import load_metric_docs
from .marts import (
    as_of_quarter,
    fund_explorer,
    fund_jcurve,
    latest_fund_performance,
    latest_portfolio_performance,
)
from .meta import dbt_generated_at, git_sha

__all__ = [
    "DEMO_DB",
    "active_source",
    "as_of_quarter",
    "dbt_generated_at",
    "fund_explorer",
    "fund_jcurve",
    "git_sha",
    "latest_fund_performance",
    "latest_portfolio_performance",
    "load_metric_docs",
    "read_sql",
]
