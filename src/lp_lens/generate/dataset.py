"""Orchestration: config in, one DataFrame per table out.

`generate_dataset` is pure with respect to the config. It touches no clock, no filesystem and no
environment variable, so the config plus the code fully determine the result. Writing to disk is
`writer.write_dataset`, kept separate so tests can assert on the data without going through
Parquet.
"""

from __future__ import annotations

from dataclasses import asdict

import pandas as pd

from .config import GeneratorConfig
from .entities import build_commitments, build_funds, build_investors, build_managers
from .flows import build_cash_flows_and_nav
from .market import build_fx_rates, build_public_index
from .streams import make_streams
from .writer import TABLE_SCHEMAS

# Columns held on the Fund dataclass as generator ground truth and deliberately not published.
_FUND_INTERNAL_FIELDS = ("life_years", "terminal_tvpi")


def _frame(name: str, rows: list[dict]) -> pd.DataFrame:
    """Build a DataFrame with the declared columns, correct even when there are no rows."""
    columns = [field.name for field in TABLE_SCHEMAS[name]]
    if not rows:
        return pd.DataFrame({column: [] for column in columns})
    return pd.DataFrame(rows)[columns]


def generate_dataset(config: GeneratorConfig) -> dict[str, pd.DataFrame]:
    """Generate every table. Same config gives the same result, always."""
    streams = make_streams(config.seed)

    managers = build_managers(config, streams["managers"])
    funds = build_funds(config, managers, streams["funds"])
    investors = build_investors(config, streams["investors"])
    commitments = build_commitments(config, funds, investors, streams["commitments"])
    cash_flows, nav = build_cash_flows_and_nav(config, funds, commitments, streams["cash_flows"], streams["nav"])
    fx_rates = build_fx_rates(config, streams["fx"])
    public_index = build_public_index(config, streams["index"])

    fund_rows = []
    for fund in funds:
        row = asdict(fund)
        for field in _FUND_INTERNAL_FIELDS:
            row.pop(field)
        fund_rows.append(row)

    return {
        "managers": _frame("managers", [asdict(m) for m in managers]),
        "funds": _frame("funds", fund_rows),
        "investors": _frame("investors", [asdict(i) for i in investors]),
        "commitments": _frame("commitments", [asdict(c) for c in commitments]),
        "cash_flows": _frame("cash_flows", cash_flows),
        "nav": _frame("nav", nav),
        "fx_rates": _frame("fx_rates", fx_rates),
        "public_index": _frame("public_index", public_index),
    }
