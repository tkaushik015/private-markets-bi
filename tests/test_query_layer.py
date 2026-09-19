"""Tests for the Streamlit query layer. No Streamlit import; no metric recomputation."""

from __future__ import annotations

import inspect
from pathlib import Path

import pandas as pd
import pytest

from lp_lens.query import (
    DEMO_DB,
    active_source,
    as_of_quarter,
    dbt_generated_at,
    fund_jcurve,
    git_sha,
    latest_fund_performance,
    latest_portfolio_performance,
    load_metric_docs,
)
from lp_lens.query import connection as connection_mod
from lp_lens.query import marts as marts_mod

REPO = Path(__file__).resolve().parents[1]


def test_query_layer_does_not_import_streamlit() -> None:
    import lp_lens.query as package
    import lp_lens.query.connection as conn
    import lp_lens.query.docs as docs
    import lp_lens.query.marts as marts
    import lp_lens.query.meta as meta

    for module in (package, conn, docs, marts, meta):
        assert "streamlit" not in module.__dict__
        source = inspect.getsource(module)
        assert "import streamlit" not in source
        assert "from streamlit" not in source


def test_query_layer_does_not_recompute_metrics() -> None:
    source = inspect.getsource(marts_mod)
    forbidden = (" / paid_in", "xirr(", "ks_pme(", "dpi + rvpi", "mean()", "median(")
    for token in forbidden:
        assert token not in source, f"query layer must not compute metrics ({token!r})"


def test_default_source_is_committed_duckdb() -> None:
    assert active_source() == "duckdb"
    assert DEMO_DB.is_file(), "app/data/demo.duckdb must be committed for Community Cloud"
    assert DEMO_DB.stat().st_size < 5 * 1024 * 1024


def test_latest_portfolio_is_mart_grain() -> None:
    frame = latest_portfolio_performance()
    assert not frame.empty
    assert frame["investor_id"].is_unique
    assert frame["is_latest_quarter"].all()
    for column in ("commitment_usd", "paid_in_usd", "unfunded_usd", "nav_usd", "tvpi", "dpi", "net_irr"):
        assert column in frame.columns
    # The query layer must not turn a NULL IRR into 0.0 (which would read as "broke even").
    source = inspect.getsource(marts_mod) + inspect.getsource(connection_mod)
    assert "fillna" not in source


def test_latest_funds_is_mart_grain() -> None:
    frame = latest_fund_performance()
    assert not frame.empty
    assert frame.duplicated(["fund_id", "investor_id"]).sum() == 0
    assert frame["is_latest_quarter"].all()
    assert {"strategy", "vintage_year", "tvpi", "net_irr", "fund_name"} <= set(frame.columns)


def test_as_of_quarter_comes_from_the_mart() -> None:
    as_of = as_of_quarter()
    assert as_of is not None
    funds = latest_fund_performance()
    assert funds["as_of_quarter"].max() == as_of


def test_jcurve_is_the_fund_mart_time_series() -> None:
    latest = latest_fund_performance()
    row = latest.iloc[0]
    series = fund_jcurve(row["fund_id"], row["investor_id"])
    assert not series.empty
    assert series["as_of_quarter"].is_monotonic_increasing
    assert series.duplicated("as_of_quarter").sum() == 0
    last = series.iloc[-1]
    assert last["tvpi"] == pytest.approx(row["tvpi"], rel=1e-12, abs=1e-12) or (
        pd.isna(last["tvpi"]) and pd.isna(row["tvpi"])
    )


def test_metric_docs_come_from_dbt_yaml() -> None:
    blocks = load_metric_docs()
    names = {b["name"] for b in blocks}
    required = {
        "as_of_convention",
        "metric_dpi",
        "metric_rvpi",
        "metric_tvpi",
        "metric_net_irr",
        "metric_ks_pme",
        "metric_paid_in",
        "metric_commitment",
        "metric_unfunded",
    }
    assert required <= names
    tvpi = next(b for b in blocks if b["name"] == "metric_tvpi")
    assert "ratio of sums" in tvpi["body"].lower()
    irr = next(b for b in blocks if b["name"] == "metric_net_irr")
    assert "NULL" in irr["body"]


def test_footer_stamps_are_available() -> None:
    assert dbt_generated_at()
    # SHA is present in a git checkout; Community Cloud may only have GITHUB_SHA.
    sha = git_sha()
    assert sha is None or len(sha) >= 7


def test_unknown_source_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LP_LENS_APP_SOURCE", "postgres")
    with pytest.raises(ValueError, match="LP_LENS_APP_SOURCE"):
        active_source()


def test_missing_demo_db_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LP_LENS_DEMO_DB", str(tmp_path / "missing.duckdb"))
    monkeypatch.setenv("LP_LENS_APP_SOURCE", "duckdb")
    with pytest.raises(FileNotFoundError, match="Demo warehouse"):
        connection_mod.read_sql("select 1")
