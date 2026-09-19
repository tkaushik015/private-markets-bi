"""Vintage and strategy benchmarking. Points are fund-mart rows, not averaged ratios."""

from __future__ import annotations

import plotly.express as px
import streamlit as st

import _bootstrap  # noqa: F401
from _ui import as_of_banner, empty_state, footer
from lp_lens.query import latest_fund_performance

st.set_page_config(page_title="Vintage & strategy", layout="wide")
st.title("Vintage & strategy benchmarking")
as_of_banner()
st.caption(
    "Each point is one fund x investor row from fct_fund_performance_quarterly "
    "(is_latest_quarter). TVPI and IRR are the mart columns. This page does not "
    "average fund ratios into a vintage or strategy TVPI."
)


@st.cache_data(ttl=300, show_spinner="Loading fund mart…")
def _funds():
    return latest_fund_performance()


funds = _funds()
if funds.empty:
    empty_state("No latest-quarter rows in fct_fund_performance_quarterly.")
    footer()
    st.stop()

left, right = st.columns(2)
strategies = ["All", *sorted(funds["strategy"].dropna().unique().tolist())]
vintages = ["All", *[str(v) for v in sorted(funds["vintage_year"].dropna().unique().tolist())]]
strategy = left.selectbox("Strategy", strategies)
vintage = right.selectbox("Vintage year", vintages)

view = funds
if strategy != "All":
    view = view.loc[view["strategy"] == strategy]
if vintage != "All":
    view = view.loc[view["vintage_year"] == int(vintage)]

if view.empty:
    empty_state("No positions match those filters.")
    footer()
    st.stop()

chart = px.scatter(
    view,
    x="vintage_year",
    y="tvpi",
    color="strategy",
    hover_name="fund_name",
    hover_data={"investor_name": True, "net_irr": ":.1%", "dpi": ":.2f", "tvpi": ":.2f"},
    labels={"vintage_year": "Vintage", "tvpi": "TVPI (mart)"},
)
chart.update_layout(height=420, legend_title="Strategy")
st.plotly_chart(chart, use_container_width=True)

st.dataframe(
    view[
        [
            "fund_name",
            "investor_name",
            "strategy",
            "vintage_year",
            "commitment_usd",
            "tvpi",
            "dpi",
            "net_irr",
            "ks_pme",
            "fund_age_years",
        ]
    ],
    hide_index=True,
    use_container_width=True,
    column_config={
        "commitment_usd": st.column_config.NumberColumn("Commitment USD", format="$%.0f"),
        "tvpi": st.column_config.NumberColumn("TVPI", format="%.2f"),
        "dpi": st.column_config.NumberColumn("DPI", format="%.2f"),
        "net_irr": st.column_config.NumberColumn("Net IRR", format="%.1%"),
        "ks_pme": st.column_config.NumberColumn("KS-PME", format="%.2f"),
        "fund_age_years": st.column_config.NumberColumn("Age (years)", format="%.1f"),
    },
)

footer()
