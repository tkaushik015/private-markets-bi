"""J-curve from the fund-mart time series. TVPI is the mart column at each quarter."""

from __future__ import annotations

import plotly.express as px
import streamlit as st

import _bootstrap  # noqa: F401
from _ui import as_of_banner, empty_state, footer
from lp_lens.query import fund_jcurve, latest_fund_performance

st.set_page_config(page_title="J-curve", layout="wide")
st.title("J-curve")
as_of_banner()
st.caption(
    "Young funds sit below 1.0x because paid-in includes management fees before NAV has "
    "caught up. The line is tvpi from fct_fund_performance_quarterly plotted against "
    "fund_age_years from the same mart."
)


@st.cache_data(ttl=300, show_spinner="Loading fund mart…")
def _funds():
    return latest_fund_performance()


funds = _funds()
if funds.empty:
    empty_state("No latest-quarter rows in fct_fund_performance_quarterly.")
    footer()
    st.stop()

labels = funds.apply(lambda r: f"{r['fund_name']} · {r['investor_name']}", axis=1)
pick = st.selectbox("Position", labels.tolist())
chosen = funds.loc[labels == pick].iloc[0]

series = fund_jcurve(chosen["fund_id"], chosen["investor_id"])
if series.empty:
    empty_state("That position has no quarterly rows in the fund mart.")
    footer()
    st.stop()

long = series.melt(
    id_vars=["as_of_quarter", "fund_age_years"],
    value_vars=["tvpi", "dpi", "rvpi"],
    var_name="metric",
    value_name="value",
)
fig = px.line(
    long,
    x="fund_age_years",
    y="value",
    color="metric",
    markers=True,
    labels={"fund_age_years": "Fund age (years)", "value": "Multiple (mart)"},
)
fig.add_hline(y=1.0, line_dash="dash", line_color="gray")
fig.update_layout(height=420)
st.plotly_chart(fig, use_container_width=True)

st.dataframe(
    series[["as_of_quarter", "fund_age_years", "paid_in_usd", "nav_usd", "dpi", "rvpi", "tvpi", "net_irr"]],
    hide_index=True,
    use_container_width=True,
    column_config={
        "paid_in_usd": st.column_config.NumberColumn("Paid-in USD", format="$%.0f"),
        "nav_usd": st.column_config.NumberColumn("NAV USD", format="$%.0f"),
        "dpi": st.column_config.NumberColumn("DPI", format="%.2f"),
        "rvpi": st.column_config.NumberColumn("RVPI", format="%.2f"),
        "tvpi": st.column_config.NumberColumn("TVPI", format="%.2f"),
        "net_irr": st.column_config.NumberColumn("Net IRR", format="%.1%"),
        "fund_age_years": st.column_config.NumberColumn("Age (years)", format="%.2f"),
    },
)

footer()
