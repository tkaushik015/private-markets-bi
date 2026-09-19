"""Portfolio Overview. KPIs are columns from fct_portfolio_performance_quarterly."""

from __future__ import annotations

import streamlit as st

import _bootstrap  # noqa: F401
from _ui import as_of_banner, empty_state, footer, format_money, format_multiple, format_rate
from lp_lens.query import latest_portfolio_performance

st.set_page_config(page_title="LP Lens", page_icon="▣", layout="wide")
st.title("Portfolio overview")
as_of_banner()


@st.cache_data(ttl=300, show_spinner="Loading portfolio mart…")
def _portfolio():
    return latest_portfolio_performance()


portfolio = _portfolio()
if portfolio.empty:
    empty_state("No latest-quarter rows in fct_portfolio_performance_quarterly.")
    footer()
    st.stop()

names = portfolio["investor_name"].tolist()
choice = st.selectbox("Limited partner", names, index=0)
row = portfolio.loc[portfolio["investor_name"] == choice].iloc[0]

k1, k2, k3, k4, k5, k6, k7 = st.columns(7)
k1.metric("Commitment", format_money(row["commitment_usd"]))
k2.metric("Paid-in", format_money(row["paid_in_usd"]))
k3.metric("Unfunded", format_money(row["unfunded_usd"]))
k4.metric("NAV", format_money(row["nav_usd"]))
k5.metric("TVPI", format_multiple(row["tvpi"]))
k6.metric("DPI", format_multiple(row["dpi"]))
k7.metric("Net IRR", format_rate(row["net_irr"]))

st.caption(
    f"{int(row['fund_count'])} funds in this LP's programme. "
    "TVPI, DPI and net IRR are the portfolio-mart columns (ratio of sums / pooled IRR), "
    "not an average of fund-level ratios."
)

st.subheader("All LPs at the latest quarter")
show = portfolio[
    [
        "investor_name",
        "investor_type",
        "fund_count",
        "commitment_usd",
        "paid_in_usd",
        "unfunded_usd",
        "nav_usd",
        "dpi",
        "tvpi",
        "net_irr",
        "ks_pme",
    ]
].copy()
st.dataframe(
    show,
    hide_index=True,
    use_container_width=True,
    column_config={
        "commitment_usd": st.column_config.NumberColumn("Commitment USD", format="$%.0f"),
        "paid_in_usd": st.column_config.NumberColumn("Paid-in USD", format="$%.0f"),
        "unfunded_usd": st.column_config.NumberColumn("Unfunded USD", format="$%.0f"),
        "nav_usd": st.column_config.NumberColumn("NAV USD", format="$%.0f"),
        "dpi": st.column_config.NumberColumn("DPI", format="%.2f"),
        "tvpi": st.column_config.NumberColumn("TVPI", format="%.2f"),
        "net_irr": st.column_config.NumberColumn("Net IRR", format="%.1%"),
        "ks_pme": st.column_config.NumberColumn("KS-PME", format="%.2f"),
    },
)

footer()
