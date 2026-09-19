"""Metric definitions rendered from warehouse/models/marts/_metric_definitions.md."""

from __future__ import annotations

import streamlit as st

import _bootstrap  # noqa: F401
from _ui import as_of_banner, empty_state, footer
from lp_lens.query import load_metric_docs

st.set_page_config(page_title="Metric definitions", layout="wide")
st.title("Metric definitions")
as_of_banner()
st.caption("These blocks are the dbt docs, not a second write-up. The app does not change the formulae.")

try:
    blocks = load_metric_docs()
except (OSError, ValueError) as exc:
    empty_state(f"Could not read the dbt metric docs: {exc}")
    footer()
    st.stop()

for block in blocks:
    with st.expander(block["title"], expanded=block["name"] in {"as_of_convention", "metric_tvpi"}):
        st.markdown(block["body"])

footer()
