"""Fund explorer. Latest row from the fund mart; drill-down is that position's quarterly mart rows."""

from __future__ import annotations

import streamlit as st

import _bootstrap  # noqa: F401
from _ui import as_of_banner, empty_state, footer, format_money, format_multiple, format_rate
from lp_lens.query import fund_jcurve, latest_fund_performance

st.set_page_config(page_title="Fund explorer", layout="wide")
st.title("Fund explorer")
as_of_banner()


@st.cache_data(ttl=300, show_spinner="Loading fund mart…")
def _funds():
    return latest_fund_performance()


funds = _funds()
if funds.empty:
    empty_state("No latest-quarter rows in fct_fund_performance_quarterly.")
    footer()
    st.stop()

search = st.text_input("Filter by fund, manager or LP")
view = funds
if search.strip():
    needle = search.strip().lower()
    mask = (
        view["fund_name"].str.lower().str.contains(needle, na=False)
        | view["manager_name"].str.lower().str.contains(needle, na=False)
        | view["investor_name"].str.lower().str.contains(needle, na=False)
    )
    view = view.loc[mask]

if view.empty:
    empty_state("No positions match that filter.")
    footer()
    st.stop()

st.dataframe(
    view[
        [
            "fund_name",
            "manager_name",
            "investor_name",
            "strategy",
            "vintage_year",
            "commitment_usd",
            "paid_in_usd",
            "nav_usd",
            "tvpi",
            "dpi",
            "net_irr",
            "ks_pme",
        ]
    ],
    hide_index=True,
    use_container_width=True,
    column_config={
        "commitment_usd": st.column_config.NumberColumn("Commitment USD", format="$%.0f"),
        "paid_in_usd": st.column_config.NumberColumn("Paid-in USD", format="$%.0f"),
        "nav_usd": st.column_config.NumberColumn("NAV USD", format="$%.0f"),
        "tvpi": st.column_config.NumberColumn("TVPI", format="%.2f"),
        "dpi": st.column_config.NumberColumn("DPI", format="%.2f"),
        "net_irr": st.column_config.NumberColumn("Net IRR", format="%.1%"),
        "ks_pme": st.column_config.NumberColumn("KS-PME", format="%.2f"),
    },
)

labels = view.apply(lambda r: f"{r['fund_name']} · {r['investor_name']}", axis=1)
pick = st.selectbox("Drill down", labels.tolist())
chosen = view.loc[labels == pick].iloc[0]

c1, c2, c3, c4 = st.columns(4)
c1.metric("TVPI", format_multiple(chosen["tvpi"]))
c2.metric("DPI", format_multiple(chosen["dpi"]))
c3.metric("Net IRR", format_rate(chosen["net_irr"]))
c4.metric("NAV", format_money(chosen["nav_usd"]))

st.caption(
    f"{chosen['strategy']} · vintage {int(chosen['vintage_year'])} · "
    f"{chosen['manager_name']} · age {float(chosen['fund_age_years']):.1f} years. "
    "Quarterly figures below are the same mart, not a recalculation."
)

series = fund_jcurve(chosen["fund_id"], chosen["investor_id"])
if series.empty:
    empty_state("No quarterly history for that position.")
else:
    st.dataframe(
        series,
        hide_index=True,
        use_container_width=True,
        column_config={
            "paid_in_usd": st.column_config.NumberColumn("Paid-in USD", format="$%.0f"),
            "distributions_usd": st.column_config.NumberColumn("Distributions USD", format="$%.0f"),
            "nav_usd": st.column_config.NumberColumn("NAV USD", format="$%.0f"),
            "dpi": st.column_config.NumberColumn("DPI", format="%.2f"),
            "rvpi": st.column_config.NumberColumn("RVPI", format="%.2f"),
            "tvpi": st.column_config.NumberColumn("TVPI", format="%.2f"),
            "net_irr": st.column_config.NumberColumn("Net IRR", format="%.1%"),
            "fund_age_years": st.column_config.NumberColumn("Age (years)", format="%.2f"),
        },
    )

footer()
