"""Shared Streamlit chrome. Formatting only — no metric arithmetic."""

from __future__ import annotations

import datetime as dt

import pandas as pd
import streamlit as st

from lp_lens.query import active_source, as_of_quarter, dbt_generated_at, git_sha


def format_money(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    return f"${float(value):,.0f}"


def format_multiple(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    return f"{float(value):.2f}x"


def format_rate(value) -> str:
    """IRR/PME. NULL stays em-dash. Never render an uncomputable rate as 0%."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    return f"{float(value) * 100:.1f}%"


def as_of_banner() -> dt.date | None:
    as_of = as_of_quarter()
    label = as_of.isoformat() if as_of else "unknown"
    st.info(
        f"**As of {label}.** Every figure is inception-to-date as at that quarter end, "
        "net of management fees, not net of carry (carry is not in the source data). "
        "Young funds show TVPI below 1.0x because of the J-curve: fees are paid in "
        "before residual value has accrued. That is not a data error."
    )
    return as_of


def empty_state(message: str) -> None:
    st.warning(message)


def footer() -> None:
    generated = dbt_generated_at() or "unknown"
    sha = git_sha() or "unknown"
    st.caption(
        f"Source: **{active_source()}** · dbt manifest generated_at **{generated}** · "
        f"git **{sha}**. Metrics are mart columns. The app does not recompute IRR, TVPI or PME."
    )
